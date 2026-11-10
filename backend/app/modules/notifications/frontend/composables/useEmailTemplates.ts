import type { ApiResponse } from '~~/app/types'

export interface EmailTemplateVariable {
  name: string
  snippet: string
}

export interface EmailTemplateSummary {
  template_key: string
  default_subject: string
  customized_locales: string[]
  disabled_locales: string[]
}

export interface EmailTemplateDetail {
  template_key: string
  locale: string
  is_custom: boolean
  is_active: boolean
  subject: string
  body_html: string
  default_subject: string
  default_body_html: string
  variables: EmailTemplateVariable[]
  updated_at: string | null
}

export interface EmailTemplateDraft {
  subject: string
  body_html: string
}

export interface EmailTemplatePreview {
  subject: string
  html: string
}

const BASE = '/api/v1/notifications/email-templates'

// Thin API wrapper; callers own loading/error UI (preview errors are
// shown inline, so every call opts out of the global error toast).
export function useEmailTemplates() {
  const api = useApi()

  const path = (key: string) => `${BASE}/${encodeURIComponent(key)}`

  async function list(): Promise<EmailTemplateSummary[]> {
    const res = await api.get<ApiResponse<EmailTemplateSummary[]>>(BASE, { errorToast: false })
    return res.data
  }

  async function get(key: string, locale: string): Promise<EmailTemplateDetail> {
    const res = await api.get<ApiResponse<EmailTemplateDetail>>(path(key), {
      query: { locale },
      errorToast: false
    })
    return res.data
  }

  async function preview(key: string, locale: string, draft: EmailTemplateDraft): Promise<EmailTemplatePreview> {
    const res = await api.post<ApiResponse<EmailTemplatePreview>>(`${path(key)}/preview`, draft, {
      query: { locale },
      errorToast: false
    })
    return res.data
  }

  async function save(
    key: string,
    locale: string,
    payload: EmailTemplateDraft & { is_active: boolean }
  ): Promise<EmailTemplateDetail> {
    const res = await api.put<ApiResponse<EmailTemplateDetail>>(path(key), payload, {
      query: { locale },
      errorToast: false
    })
    return res.data
  }

  async function reset(key: string, locale: string): Promise<EmailTemplateDetail> {
    const res = await api.del<ApiResponse<EmailTemplateDetail>>(path(key), {
      query: { locale },
      errorToast: false
    })
    return res.data
  }

  async function sendTest(key: string, locale: string, draft: EmailTemplateDraft): Promise<string> {
    const res = await api.post<ApiResponse<{ sent_to: string }>>(`${path(key)}/test`, draft, {
      query: { locale },
      errorToast: false
    })
    return res.data.sent_to
  }

  return { list, get, preview, save, reset, sendTest }
}
