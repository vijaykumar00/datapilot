/**
 * Sample data: a small, realistic sales export bundled with the app so anyone
 * can try Tallis without a file of their own.  It goes through the normal
 * upload path, so everything (questions, reports, spreadsheet) works on it.
 */
export const SAMPLE_FILE = { path: '/samples/sample-sales.csv', name: 'sample-sales.csv' }

export const SAMPLE_QUESTIONS = [
  'Total revenue by region',
  'Top 3 products by revenue',
  'Revenue by month',
  'How many orders in the West',
]

export async function loadSampleData(uploadFile) {
  let res
  try {
    res = await fetch(SAMPLE_FILE.path)
  } catch {
    return { success: false, error: "The sample file couldn't be downloaded. Check your connection." }
  }
  if (!res.ok) return { success: false, error: "The sample file couldn't be downloaded." }
  const blob = await res.blob()
  const file = new File([blob], SAMPLE_FILE.name, { type: 'text/csv' })
  return uploadFile(file)
}
