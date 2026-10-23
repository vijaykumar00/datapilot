/**
 * Reports: one place for automatic data insights and the branded report
 * builder (formerly the separate Dashboard and Report builder pages).
 */
import { lazy, Suspense, useEffect } from 'react'
import { useDataPilot } from '../../hooks/useDataPilot'
import { FileText, Sparkles } from 'lucide-react'
import SubNav, { useSubView } from './SubNav'
import DashboardView from './DashboardView'
import { Skeleton } from '../ui'

const ReportView = lazy(() => import('./ReportView'))
const ChartRenderer = lazy(() => import('../ChartRenderer'))

const VIEWS = [
  { id: 'insights', label: 'Insights', icon: Sparkles },
  { id: 'builder', label: 'Report builder', icon: FileText },
]

export default function ReportsPage() {
  const [view, setView] = useSubView(VIEWS)
  const { files, activeFileId, loadPreviewFile } = useDataPilot()
  const activeFile = files.find((f) => f.file_id === activeFileId) || files[0]

  // Files restored after a reload only carry a summary; load the full profile
  // (insights, column types) the first time Reports needs it.
  useEffect(() => {
    if (activeFile?.metadata?.restored) loadPreviewFile(activeFile.file_id)
  }, [activeFile?.file_id, activeFile?.metadata?.restored, loadPreviewFile])
  return (
    <div className="flex h-full flex-col">
      <SubNav label="Reports" views={VIEWS} current={view} onSelect={setView} />
      <div className="min-h-0 flex-1 overflow-hidden">
        {view === 'insights' ? (
          <DashboardView ChartRenderer={ChartRenderer} />
        ) : (
          <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-6 w-48" /><Skeleton className="h-64 w-full" /></div>}>
            <ReportView />
          </Suspense>
        )}
      </div>
    </div>
  )
}
