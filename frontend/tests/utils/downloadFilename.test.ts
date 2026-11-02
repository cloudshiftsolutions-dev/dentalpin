// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { filenameFromContentDisposition } from '~~/app/utils/downloadFilename'

describe('filenameFromContentDisposition', () => {
  it('drops the quotes around a quoted name (DENTALPIN-38)', () => {
    expect(filenameFromContentDisposition('attachment; filename="prescription_f912b081.pdf"', 'x.pdf'))
      .toBe('prescription_f912b081.pdf')
  })

  it('reads a bare name and ignores later parameters', () => {
    expect(filenameFromContentDisposition('attachment; filename=recalls.csv; size=10', 'x')).toBe('recalls.csv')
  })

  it('prefers the RFC 5987 UTF-8 form', () => {
    expect(filenameFromContentDisposition(
      'attachment; filename="factura.pdf"; filename*=UTF-8\'\'factura_Jos%C3%A9.pdf',
      'x.pdf'
    )).toBe('factura_José.pdf')
  })

  it('unescapes quotes inside a quoted name and strips path separators', () => {
    expect(filenameFromContentDisposition('attachment; filename="a\\"b/c.pdf"', 'x.pdf')).toBe('a"b_c.pdf')
  })

  it('falls back when the header is missing or empty', () => {
    expect(filenameFromContentDisposition(null, 'document.pdf')).toBe('document.pdf')
    expect(filenameFromContentDisposition('inline', 'document.pdf')).toBe('document.pdf')
    expect(filenameFromContentDisposition('attachment; filename=""', 'document.pdf')).toBe('document.pdf')
  })
})
