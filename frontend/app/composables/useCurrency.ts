// Single source of truth for rendering money in the frontend.
// - Currency comes from `currentClinic.currency` (one clinic = one currency).
// - Locale follows the user's UI language (Intl handles separators/symbols),
//   except rupees, which always use Indian grouping.
//
// Components that render money should call `format()` (or use the `<Money>`
// component, which delegates here). No callsite should hardcode a currency
// or inline `Intl.NumberFormat`.

export function useCurrency() {
  const { currentClinic } = useClinic()
  const { currentLocale } = useLocale()

  const currency = computed(() => currentClinic.value?.currency || DEFAULT_CURRENCY)

  function format(amount: number | string | null | undefined): string {
    if (amount == null || amount === '') return '—'
    const value = typeof amount === 'string' ? Number(amount) : amount
    if (Number.isNaN(value)) return '—'
    return new Intl.NumberFormat(moneyLocale(currency.value, currentLocale.value), {
      style: 'currency',
      currency: currency.value
    }).format(value)
  }

  function symbol(): string {
    const parts = new Intl.NumberFormat(moneyLocale(currency.value, currentLocale.value), {
      style: 'currency',
      currency: currency.value,
      currencyDisplay: 'narrowSymbol'
    }).formatToParts(0)
    return parts.find(p => p.type === 'currency')?.value ?? currency.value
  }

  return {
    format,
    symbol,
    currency
  }
}
