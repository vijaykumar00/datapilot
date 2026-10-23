/**
 * Saved: everything the user chose to keep — answers saved from chat and
 * generated reports (formerly two separate pages).
 */
import { lazy, Suspense } from 'react'
import { Bookmark, Files } from 'lucide-react'
import SubNav, { useSubView } from './SubNav'
import { Skeleton } from '../ui'

const SavedAnalyses = lazy(() => import('../SavedAnalyses'))
const SavedReports = lazy(() => import('../SavedReports'))

const VIEWS = [
  { id: 'answers', label: 'Answers', icon: Bookmark },
  { id: 'reports', label: 'Reports', icon: Files },
]

export default function SavedPage() {
  const [view, setView] = useSubView(VIEWS)
  return (
    <div className="flex h-full flex-col">
      <SubNav label="Saved items" views={VIEWS} current={view} onSelect={setView} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-6 w-48" /><Skeleton className="h-40 w-full" /></div>}>
          {view === 'answers' ? <SavedAnalyses /> : <SavedReports />}
        </Suspense>
      </div>
    </div>
  )
}
