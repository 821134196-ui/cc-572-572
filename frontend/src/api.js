import { reactive } from 'vue'

export const store = reactive({
  user: JSON.parse(localStorage.getItem('lab_user') || 'null'),
  setUser(u) {
    this.user = u
    if (u) localStorage.setItem('lab_user', JSON.stringify(u))
    else localStorage.removeItem('lab_user')
  }
})

async function request(method, path, body) {
  const headers = {}
  const opts = { method, headers }
  if (store.user) headers.Authorization = `Bearer ${store.user.token}`
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(path, opts)
  let data = null
  const text = await resp.text()
  if (text) data = JSON.parse(text)
  if (!resp.ok) {
    const err = new Error()
    err.status = resp.status
    err.data = data
    if (data?.detail) {
      if (typeof data.detail === 'object' && data.detail.message) {
        err.message = data.detail.message
        err.detail = data.detail
      } else {
        err.message = String(data.detail)
      }
    } else {
      err.message = `请求失败 (${resp.status})`
    }
    throw err
  }
  return data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b ?? {}),
  upload: async (p, formData) => {
    const resp = await fetch(p, {
      method: 'POST',
      headers: { Authorization: `Bearer ${store.user.token}` },
      body: formData
    })
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}))
      throw new Error(d.detail || '上传失败')
    }
    return resp.json()
  }
}
