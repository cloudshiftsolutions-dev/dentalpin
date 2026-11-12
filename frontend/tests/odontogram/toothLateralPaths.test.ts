import { describe, expect, it } from 'vitest'
import { getLateralPath } from '#module-layers/odontogram/frontend/components/odontogram/ToothSVGPaths'

const viewBoxHeight = (tooth: number) => Number(getLateralPath(tooth).viewBox.split(' ')[3])

describe('lateral tooth shapes', () => {
  it('draws first premolars at the same height as second premolars', () => {
    for (const [first, second] of [[14, 15], [24, 25], [34, 35], [44, 45]] as const) {
      expect(viewBoxHeight(first)).toBe(viewBoxHeight(second))
    }
  })

  it('gives the first premolars a single root', () => {
    for (const tooth of [14, 24, 34, 44]) {
      const paths = getLateralPath(tooth)
      expect(paths.root).toBeTruthy()
      expect(paths.roots).toBeUndefined()
    }
  })

  it('uses lower anatomy for 34, 44, 37, 38, 47 and 48', () => {
    for (const [lower, upper] of [[34, 14], [44, 14], [37, 17], [47, 17], [38, 18], [48, 18]] as const) {
      expect(getLateralPath(lower)).not.toBe(getLateralPath(upper))
    }
    expect(getLateralPath(37)).toBe(getLateralPath(47))
    expect(getLateralPath(38)).toBe(getLateralPath(48))
  })

  it('leaves the other teeth and the primary dentition unchanged', () => {
    for (const [lower, upper] of [[46, 16], [36, 16], [45, 15], [41, 11], [75, 55], [84, 54]] as const) {
      expect(getLateralPath(lower)).toBe(getLateralPath(upper))
    }
  })
})
