import React from 'react'
import MarketingHeader from '../../components/marketing/MarketingHeader'
import MarketingFooter from '../../components/marketing/MarketingFooter'
import DocumentMetadata from '../../components/marketing/DocumentMetadata'

export default function SecurityPage() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
      <DocumentMetadata 
        title="Data Security, Encryption and Workspace Isolation" 
        description="Learn about DataPilot data security: application-level encrypted API key vaulting, workspace tenant isolation, and secure user sessions."
      />
      <MarketingHeader />
      <main className="flex-1 max-w-7xl mx-auto px-6 py-20 z-10 relative w-full text-center">
        <h2 className="text-3xl md:text-5xl font-black text-white tracking-tight">Security</h2>
        <p className="text-slate-400 text-xs mt-3">Security and encryption policy disclosures coming in Sprint 3.3.</p>
      </main>
      <MarketingFooter />
    </div>
  )
}
