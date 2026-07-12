import React from 'react'
import MarketingHeader from '../../components/marketing/MarketingHeader'
import MarketingFooter from '../../components/marketing/MarketingFooter'
import DocumentMetadata from '../../components/marketing/DocumentMetadata'

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
      <DocumentMetadata 
        title="Simple, Transparent Plans & Pricing" 
        description="Choose a plan that fits your analysis needs. From our free guest mode to teams and custom configurations."
      />
      <MarketingHeader />
      <main className="flex-1 max-w-7xl mx-auto px-6 py-20 z-10 relative w-full text-center">
        <h2 className="text-3xl md:text-5xl font-black text-white tracking-tight">Pricing</h2>
        <p className="text-slate-400 text-xs mt-3">Plans matrix coming in Sprint 3.3.</p>
      </main>
      <MarketingFooter />
    </div>
  )
}
