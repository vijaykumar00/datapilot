import React from 'react'
import MarketingHeader from '../../components/marketing/MarketingHeader'
import MarketingFooter from '../../components/marketing/MarketingFooter'
import DocumentMetadata from '../../components/marketing/DocumentMetadata'

export default function ContactPage() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
      <DocumentMetadata 
        title="Contact Support & Sales" 
        description="Have questions? Reach out to the DataPilot team for technical support, organization licensing, or sales."
      />
      <MarketingHeader />
      <main className="flex-1 max-w-7xl mx-auto px-6 py-20 z-10 relative w-full text-center">
        <h2 className="text-3xl md:text-5xl font-black text-white tracking-tight">Contact</h2>
        <p className="text-slate-400 text-xs mt-3">Failsafe support forms and contact portals coming in Sprint 3.3.</p>
      </main>
      <MarketingFooter />
    </div>
  )
}
