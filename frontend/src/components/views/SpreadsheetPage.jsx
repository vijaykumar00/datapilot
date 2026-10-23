/**
 * Spreadsheet: browse, search, edit and clean the rows of an uploaded file.
 * Questions about the data live on the Ask AI page.
 */
import { lazy, Suspense, useEffect } from 'react'
import { useDataPilot } from '../../hooks/useDataPilot'
import { Skeleton } from '../ui'

const DataPreview = lazy(() => import('../DataPreview'))

export default function SpreadsheetPage() {
  const { files, previewFileId, setPreviewFile } = useDataPilot()

  // Open the first file automatically so the page is never blank when data exists.
  useEffect(() => {
    if (!previewFileId && files.length) setPreviewFile(files[0].file_id)
  }, [previewFileId, files, setPreviewFile])

  return (
    <div className="flex h-full flex-col">
      {files.length > 1 && (
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-line bg-surface px-4 py-2 sm:px-5">
          <label htmlFor="spreadsheet-file" className="text-sm text-muted">File</label>
          <select
            id="spreadsheet-file"
            className="input h-9 min-w-0 flex-1 sm:w-72 sm:flex-none"
            value={previewFileId || ''}
            onChange={(e) => setPreviewFile(e.target.value)}
          >
            {!previewFileId && <option value="">Choose a file</option>}
            {files.map((f) => <option key={f.file_id} value={f.file_id}>{f.filename}</option>)}
          </select>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-hidden">
        <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-6 w-48" /><Skeleton className="h-72 w-full" /></div>}>
          <DataPreview />
        </Suspense>
      </div>
    </div>
  )
}
