export const DEFAULT_CURRENCY = 'INR'

// Rupee amounts use Indian digit grouping (₹1,64,000.00) whatever the UI language.
export function moneyLocale(currency: string, uiLocale: string): string {
  return currency === 'INR' ? 'en-IN' : uiLocale
}
