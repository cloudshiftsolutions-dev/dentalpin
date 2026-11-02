<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { RecallIntervalUnit, RecallSettings } from '../composables/useRecalls'
import { RECALL_INTERVAL_MAX, RECALL_INTERVAL_UNITS } from '../utils/recallInterval'
import { errorDetail } from '~~/app/utils/error'

const { t } = useI18n()
const toast = useToast()
const recallsApi = useRecalls()
const { getCategoryLabel } = useTreatmentCatalog()
const { categories: catalogCategories, getCategoryName, fetchCategories } = useCatalog()

function resolveCategoryName(key: string): string {
  const cat = catalogCategories.value.find(c => c.key === key)
  if (cat) return getCategoryName(cat)
  return t(getCategoryLabel(key))
}

const settings = ref<RecallSettings | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)

const reasons = ['hygiene', 'checkup', 'ortho_review', 'implant_review', 'post_op', 'treatment_followup', 'other'] as const

async function load() {
  isLoading.value = true
  try {
    const res = await recallsApi.getSettings()
    settings.value = res.data
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  load()
  fetchCategories()
})

const unitOptions = computed(() =>
  RECALL_INTERVAL_UNITS.map(unit => ({ value: unit, label: t(`recalls.units.${unit}`) }))
)

function unitOf(reason: string): RecallIntervalUnit {
  return settings.value?.reason_interval_units?.[reason] ?? 'month'
}

function intervalError(reason: string): string | undefined {
  const value = settings.value?.reason_intervals[reason]
  const max = RECALL_INTERVAL_MAX[unitOf(reason)]
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > max) {
    return t('recalls.settings.intervalRange', { max, unit: t(`recalls.units.${unitOf(reason)}`) })
  }
  return undefined
}

const hasIntervalErrors = computed(() => reasons.some(r => intervalError(r)))

async function save() {
  if (!settings.value || isSaving.value || hasIntervalErrors.value) return
  isSaving.value = true
  try {
    const res = await recallsApi.updateSettings({
      reason_intervals: settings.value.reason_intervals,
      reason_interval_units: settings.value.reason_interval_units,
      category_to_reason: settings.value.category_to_reason,
      auto_suggest_on_treatment_completed: settings.value.auto_suggest_on_treatment_completed,
      auto_link_on_appointment_scheduled: settings.value.auto_link_on_appointment_scheduled
    })
    settings.value = res.data
    toast.add({ title: t('recalls.settings.saved'), color: 'success' })
  } catch (e) {
    toast.add({ title: t('common.error'), description: errorDetail(e), color: 'error' })
  } finally {
    isSaving.value = false
  }
}

function ensureInterval(reason: string) {
  if (!settings.value) return
  if (typeof settings.value.reason_intervals[reason] !== 'number') {
    settings.value.reason_intervals[reason] = 6
  }
  settings.value.reason_interval_units ??= {}
  if (!settings.value.reason_interval_units[reason]) {
    settings.value.reason_interval_units[reason] = 'month'
  }
}

watch(settings, () => {
  if (!settings.value) return
  for (const r of reasons) ensureInterval(r)
}, { deep: true })

const categoryRows = computed(() => {
  if (!settings.value) return []
  return Object.entries(settings.value.category_to_reason).map(([key, reason]) => ({ key, reason }))
})

const newCategoryKey = ref('')
const newCategoryReason = ref<(typeof reasons)[number]>('hygiene')

function addCategory() {
  if (!settings.value || !newCategoryKey.value) return
  settings.value.category_to_reason = {
    ...settings.value.category_to_reason,
    [newCategoryKey.value]: newCategoryReason.value
  }
  newCategoryKey.value = ''
}

function removeCategory(key: string) {
  if (!settings.value) return
  const { [key]: _removed, ...next } = settings.value.category_to_reason
  settings.value.category_to_reason = next
}
</script>

<template>
  <div class="space-y-4">
    <div>
      <h2 class="text-h2">
        {{ t('recalls.settings.title') }}
      </h2>
      <p class="text-subtle">
        {{ t('recalls.settings.description') }}
      </p>
    </div>

    <USkeleton
      v-if="isLoading || !settings"
      class="h-32 w-full"
    />

    <template v-else>
      <UCard>
        <template #header>
          <h3 class="text-h3">
            {{ t('recalls.settings.intervals') }}
          </h3>
          <p class="text-caption text-subtle mt-1">
            {{ t('recalls.settings.intervalsHelp') }}
          </p>
        </template>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <UFormField
            v-for="r in reasons"
            :key="r"
            :label="t(`recalls.reasons.${r}`)"
            :error="intervalError(r)"
          >
            <div class="flex gap-2">
              <UInput
                v-model.number="settings.reason_intervals[r]"
                type="number"
                inputmode="numeric"
                min="0"
                :max="RECALL_INTERVAL_MAX[unitOf(r)]"
                step="1"
                class="w-24 shrink-0"
                :aria-label="t('recalls.settings.intervalValue', { reason: t(`recalls.reasons.${r}`) })"
              />
              <USelect
                v-model="settings.reason_interval_units[r]"
                :items="unitOptions"
                value-key="value"
                label-key="label"
                class="flex-1 min-w-0"
                :aria-label="t('recalls.settings.intervalUnit', { reason: t(`recalls.reasons.${r}`) })"
              />
            </div>
          </UFormField>
        </div>
      </UCard>

      <UCard>
        <template #header>
          <h3 class="text-h3">
            {{ t('recalls.settings.categoryMap') }}
          </h3>
        </template>
        <ul class="divide-y divide-default">
          <li
            v-for="row in categoryRows"
            :key="row.key"
            class="flex items-center justify-between gap-3 py-2"
          >
            <span class="font-mono text-sm">{{ resolveCategoryName(row.key) }}</span>
            <span class="text-subtle">→</span>
            <span class="flex-1">{{ t(`recalls.reasons.${row.reason}`) }}</span>
            <UButton
              icon="i-lucide-trash-2"
              :aria-label="t('common.delete')"
              variant="ghost"
              color="error"
              size="xs"
              @click="removeCategory(row.key)"
            />
          </li>
        </ul>
        <div class="flex gap-2 mt-3">
          <UInput
            v-model="newCategoryKey"
            :placeholder="t('recalls.settings.categoryKeyPlaceholder')"
            class="flex-1"
          />
          <USelectMenu
            v-model="newCategoryReason"
            :items="reasons.map(r => ({ value: r, label: t(`recalls.reasons.${r}`) }))"
            value-key="value"
            label-key="label"
          />
          <UButton
            icon="i-lucide-plus"
            :aria-label="t('common.add')"
            color="primary"
            variant="soft"
            :disabled="!newCategoryKey"
            @click="addCategory"
          />
        </div>
      </UCard>

      <UCard>
        <div class="space-y-3">
          <UFormField :label="t('recalls.settings.autoSuggest')">
            <USwitch v-model="settings.auto_suggest_on_treatment_completed" />
          </UFormField>
          <UFormField :label="t('recalls.settings.autoLink')">
            <USwitch v-model="settings.auto_link_on_appointment_scheduled" />
          </UFormField>
        </div>
      </UCard>

      <div class="flex justify-end">
        <UButton
          color="primary"
          :loading="isSaving"
          :disabled="hasIntervalErrors"
          @click="save"
        >
          {{ t('recalls.actions.save') }}
        </UButton>
      </div>
    </template>
  </div>
</template>
