/**
 * File name for a blob download, read from the response's
 * ``Content-Disposition`` header (RFC 6266).
 *
 * Prefers the RFC 5987 ``filename*=UTF-8''…`` form, then a quoted or bare
 * ``filename=``. Quotes never leak into the result: a stray ``"`` is
 * rewritten to ``_`` by browsers, turning ``x.pdf"`` into an unopenable
 * ``x.pdf_`` (DENTALPIN-38). Falls back when the header is missing or the
 * name is unusable.
 */
export function filenameFromContentDisposition(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback

  const extended = header.match(/filename\*\s*=\s*([^;]+)/i)?.[1]?.trim()
  if (extended) {
    const encoded = extended.replace(/^"(.*)"$/, '$1').replace(/^[\w-]*'[\w-]*'/, '')
    try {
      const name = sanitize(decodeURIComponent(encoded))
      if (name) return name
    } catch {
      // Malformed percent-encoding: fall through to the plain parameter.
    }
  }

  const plain = header.match(/(?:^|;)\s*filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]*))/i)
  if (plain) {
    const raw = plain[1] !== undefined ? plain[1].replace(/\\(.)/g, '$1') : (plain[2] ?? '')
    const name = sanitize(raw)
    if (name) return name
  }
  return fallback
}

function sanitize(name: string): string {
  return name
    .trim()
    .replace(/^"+|"+$/g, '')
    .replace(/[\\/]/g, '_')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .trim()
}
