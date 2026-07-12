import React from 'react'
import MarketingHeader from '../../components/marketing/MarketingHeader'
import MarketingFooter from '../../components/marketing/MarketingFooter'
import DocumentMetadata from '../../components/marketing/DocumentMetadata'

export default function UseCasesPage() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
      <DocumentMetadata 
        title="SaaS Analytics Use Cases" 
        description="Explore role-specific and industry analytics templates for sales, inventory, finance, healthcare, and operations."
      />
      <MarketingHeader />
      <main className="flex-1 max-w-7xl mx-auto px-6 py-20 z-10 relative w-full text-center">
        <h2 className="text-3xl md:text-5xl font-black text-white tracking-tight">Use Cases</h2>
        <p className="text-slate-400 text-xs mt-3">Industry-specific templates coming in Sprint 3.3.</p>
      </main>
      <MarketingFooter />
    </div>
  )
}
