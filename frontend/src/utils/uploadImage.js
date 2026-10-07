const API_BASE_URL = 'http://localhost:8000'

export const uploadImage = async (file) => {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/api/uploads/image`, {
    method: 'POST',
    body: formData
  })

  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || 'Failed to upload the image')
  return data.url
}

export const uploadImages = async (files) => {
  if (!files.length) return []

  const formData = new FormData()
  files.forEach(file => formData.append('files', file))

  const response = await fetch(`${API_BASE_URL}/api/uploads/images`, {
    method: 'POST',
    body: formData
  })

  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || 'Failed to upload the images')
  return data.urls
}
