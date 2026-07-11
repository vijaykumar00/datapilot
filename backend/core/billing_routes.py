import os
import uuid
import datetime
import logging
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from core.db import get_db
from core.request_identity import get_caller, CallerContext
from core.models import (
    Workspace, Plan, BillingCustomer, Subscription, 
    SubscriptionEvent, WebhookEvent, AuditLog
)

logger = logging.getLogger("datapilot.billing")
router = APIRouter(prefix="/billing", tags=["billing"])

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Initialize stripe
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("Stripe client initialized in TEST/LIVE mode.")
else:
    logger.warning("STRIPE_SECRET_KEY not set. Operating in Stripe SANDBOX MOCK MODE.")


@router.post("/checkout")
def create_checkout_session(
    payload: dict,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db)
):
    """
    Create a Stripe Checkout session.
    """
    if not caller.is_authenticated:
        raise HTTPException(status_code=401, detail="Authentication required for checkout")

    plan_id = payload.get("plan_id", "pro")
    workspace_id = caller.workspace_id

    # Verify workspace exists
    workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Get Plan details from DB
    plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan tier")

    # Retrieve or create stripe customer ID
    customer_record = db.query(BillingCustomer).filter(
        BillingCustomer.workspace_id == workspace_id
    ).first()

    customer_id = customer_record.stripe_customer_id if customer_record else None

    # Standard Mock fallback if no Stripe configuration is present
    if not STRIPE_SECRET_KEY:
        # Mock mode: return success callback directly as mock checkout URL
        mock_checkout_url = f"{FRONTEND_URL}/app/settings/billing?session_id=mock_session_{uuid.uuid4()}&workspace_id={workspace_id}&plan_id={plan_id}"
        
        # Simulate active state inside DB for local developer convenience
        if not customer_id:
            customer_id = f"cus_mock_{uuid.uuid4().hex[:12]}"
            db.add(BillingCustomer(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                stripe_customer_id=customer_id
            ))
        
        # Update or create mock subscription
        sub = db.query(Subscription).filter(Subscription.workspace_id == workspace_id).first()
        if not sub:
            sub = Subscription(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                stripe_subscription_id=f"sub_mock_{uuid.uuid4().hex[:12]}",
                status="active",
                plan_id=plan_id,
                current_period_start=datetime.datetime.utcnow(),
                current_period_end=datetime.datetime.utcnow() + datetime.timedelta(days=30)
            )
            db.add(sub)
        else:
            sub.status = "active"
            sub.plan_id = plan_id
            sub.current_period_end = datetime.datetime.utcnow() + datetime.timedelta(days=30)

        # Update workspace plan tier reference
        workspace.plan_tier = plan_id
        
        # Log audit entry
        db.add(AuditLog(
            id=str(uuid.uuid4()),
            user_id=caller.user_id,
            workspace_id=workspace_id,
            event_type="BILLING_CHECKOUT_SUCCESS",
            description=f"Mock Checkout successfully completed for plan '{plan_id}'"
        ))
        db.commit()
        return {"checkout_url": mock_checkout_url}

    try:
        # Create real Stripe customer if needed
        if not customer_id:
            stripe_customer = stripe.Customer.create(
                email=caller.user.email,
                metadata={"workspace_id": workspace_id}
            )
            customer_id = stripe_customer.id
            db.add(BillingCustomer(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                stripe_customer_id=customer_id
            ))
            db.commit()

        # Map plan_id to price ID (in test mode, you can map specific price IDs)
        # For simplicity, fallback to an ad-hoc created mock price or standard config
        price_id = os.getenv(f"STRIPE_PRICE_{plan_id.upper()}", "price_placeholder")

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"DataPilot {plan.name} Subscription",
                    },
                    "unit_amount": plan.monthly_price_cents,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{FRONTEND_URL}/app/settings/billing?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/app/settings/billing?canceled=true",
            client_reference_id=workspace_id,
            metadata={"plan_id": plan_id}
        )

        return {"checkout_url": session.url}

    except Exception as e:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal")
def create_portal_session(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db)
):
    """
    Create a Stripe Customer Portal Session.
    """
    if not caller.is_authenticated:
        raise HTTPException(status_code=401, detail="Authentication required")

    customer_record = db.query(BillingCustomer).filter(
        BillingCustomer.workspace_id == caller.workspace_id
    ).first()

    if not customer_record:
        raise HTTPException(status_code=404, detail="No billing relationship exists for this workspace")

    if not STRIPE_SECRET_KEY:
        # Mock portal redirects back to billing dashboard
        return {"portal_url": f"{FRONTEND_URL}/app/settings/billing"}

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_record.stripe_customer_id,
            return_url=f"{FRONTEND_URL}/app/settings/billing"
        )
        return {"portal_url": session.url}
    except Exception as e:
        logger.exception("Stripe portal session creation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db)
):
    """
    Process Stripe Webhooks. Ensures webhook signature verification and processed event idempotency.
    """
    payload = await request.body()
    
    if not STRIPE_SECRET_KEY:
        # Development mode bypass/mocks
        return {"status": "skipped", "reason": "No stripe key configured"}

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event.id
    
    # ── Webhook Idempotency Check ─────────────────────────────────────────────
    existing_event = db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == event_id).first()
    if existing_event:
        return {"status": "ok", "detail": "Already processed"}

    # Log new webhook event
    db.add(WebhookEvent(id=str(uuid.uuid4()), stripe_event_id=event_id, processed=True))
    db.commit()

    event_type = event.type
    data_object = event.data.object

    logger.info(f"Received Stripe webhook event: {event_type} [id={event_id}]")

    # ── Event handlers ────────────────────────────────────────────────────────
    if event_type == "checkout.session.completed":
        workspace_id = data_object.get("client_reference_id")
        stripe_sub_id = data_object.get("subscription")
        customer_id = data_object.get("customer")
        
        # Load subscription details from Stripe
        stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
        
        # Map plan_id metadata
        plan_id = data_object.get("metadata", {}).get("plan_id", "pro")

        # Create or update customer record
        if workspace_id:
            customer_record = db.query(BillingCustomer).filter(BillingCustomer.workspace_id == workspace_id).first()
            if not customer_record:
                db.add(BillingCustomer(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    stripe_customer_id=customer_id
                ))

            # Create or update subscription
            sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_sub_id).first()
            if not sub:
                db.add(Subscription(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    stripe_subscription_id=stripe_sub_id,
                    status=stripe_sub.status,
                    plan_id=plan_id,
                    current_period_start=datetime.datetime.utcfromtimestamp(stripe_sub.current_period_start),
                    current_period_end=datetime.datetime.utcfromtimestamp(stripe_sub.current_period_end)
                ))
            
            # Update workspace plan_tier reference
            workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
            if workspace:
                workspace.plan_tier = plan_id

            db.add(AuditLog(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                event_type="BILLING_SUBSCRIPTION_CREATED",
                description=f"Subscription created successfully for plan '{plan_id}'"
            ))
            db.commit()

    elif event_type in ["customer.subscription.updated", "customer.subscription.deleted"]:
        stripe_sub_id = data_object.get("id")
        status = data_object.get("status")
        cancel_at_period_end = data_object.get("cancel_at_period_end", False)

        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_sub_id).first()
        if sub:
            sub.status = status
            sub.cancel_at_period_end = cancel_at_period_end
            sub.current_period_start = datetime.datetime.utcfromtimestamp(data_object.get("current_period_start"))
            sub.current_period_end = datetime.datetime.utcfromtimestamp(data_object.get("current_period_end"))
            
            # If subscription was deleted/canceled, revert workspace plan_tier to free
            if status in ["canceled", "unpaid"]:
                workspace = db.query(Workspace).filter(Workspace.workspace_id == sub.workspace_id).first()
                if workspace:
                    workspace.plan_tier = "free"

            db.add(SubscriptionEvent(
                id=str(uuid.uuid4()),
                stripe_subscription_id=stripe_sub_id,
                event_type=event_type,
                payload=str(data_object)
            ))
            
            db.add(AuditLog(
                id=str(uuid.uuid4()),
                workspace_id=sub.workspace_id,
                event_type="BILLING_SUBSCRIPTION_UPDATED",
                description=f"Subscription status updated to '{status}'"
            ))
            db.commit()

    return {"status": "ok"}
