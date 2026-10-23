import { useNavigate } from 'react-router-dom'
import Dialog from '../ui/Dialog'
import FileUploader from '../FileUploader'
import { Button } from '../ui'
import { useDataPilot } from '../../hooks/useDataPilot'

/** Upload from anywhere in the workspace (sidebar button, Ctrl+U, empty states). */
export default function UploadDialog({ open, onClose }) {
  const navigate = useNavigate()
  const { files } = useDataPilot()
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Upload data"
      description="CSV, XLSX or XLS. Large files keep processing in the background — you can close this window."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button
            variant="primary"
            disabled={!files.length}
            onClick={() => { onClose(); navigate('/app/analyze') }}
          >
            Ask questions about your data
          </Button>
        </>
      }
    >
      <FileUploader />
    </Dialog>
  )
}
