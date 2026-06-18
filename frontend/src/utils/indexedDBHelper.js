/**
 * indexedDBHelper.js — Promisified IndexedDB wrapper for large client-side message persistence.
 */

const DB_NAME = 'datapilot_db'
const STORE_NAME = 'messages'
const DB_VERSION = 1

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)

    request.onupgradeneeded = (event) => {
      const db = event.target.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
  })
}

export const indexedDBHelper = {
  async get(key) {
    try {
      const db = await openDB()
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readonly')
        const store = transaction.objectStore(transaction.objectStoreNames[0])
        const request = store.get(key)

        request.onerror = () => reject(request.error)
        request.onsuccess = () => resolve(request.result || null)
      })
    } catch (err) {
      console.error('Failed to read from IndexedDB:', err)
      return null
    }
  },

  async set(key, value) {
    try {
      const db = await openDB()
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite')
        const store = transaction.objectStore(transaction.objectStoreNames[0])
        const request = store.put(value, key)

        request.onerror = () => reject(request.error)
        request.onsuccess = () => resolve(true)
      })
    } catch (err) {
      console.error('Failed to write to IndexedDB:', err)
      return false
    }
  },

  async delete(key) {
    try {
      const db = await openDB()
      return new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE_NAME, 'readwrite')
        const store = transaction.objectStore(transaction.objectStoreNames[0])
        const request = store.delete(key)

        request.onerror = () => reject(request.error)
        request.onsuccess = () => resolve(true)
      })
    } catch (err) {
      console.error('Failed to delete from IndexedDB:', err)
      return false
    }
  }
}
