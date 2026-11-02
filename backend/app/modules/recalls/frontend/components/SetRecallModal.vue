<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { RecallIntervalUnit, RecallReason, RecallPriority, RecallSettings, Recall } from '../composables/useRecalls'
import {
  isValidRecallInterval,
  RECALL_INTERVAL_MAX,
  RECALL_INTERVAL_UNITS,
  recallMonthOf,
  recallTimingFromInterval
} from '../utils/recallInterval'
import { errorDetail } from '~~/app/utils/error'

interface Props {
  open: boolean
  patientId: string
  /** Pre-fill from a treatment-plan / odontogram action. */
  initialReason?: RecallReason
  initialNote?: string
  initialPriority?: RecallPriority
  initialAssignedProfessionalId?: string | null
  initialDueMonth?: string // YYYY-MM-01
  initialTreatmentId?: string | null
  initialTreatmentCategoryKey?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  initialReason: 'hygiene',
  initialPriority: 'normal'
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': [recall: Recall]
}>()

const { t, locale } = useI18n()
const toast = useToast()
const recallsApi = useRecalls()

const isSubmitting = ref(false)
const reason = ref<RecallReason>(props.initialReason)
const priority = ref<RecallPriority>(props.initialPriority)
const dueMonth = ref<string>(props.initialDueMonth ?? defaultDueMonth())
const dueDate = ref<string>('')
const note = ref<string>(props.initialNote ?? '')
const assignedProfessionalId = ref<string | null>(props.initialAssignedProfessionalId ?? null)

function defaultDueMonth(): string {
  return recallTimingFromInterval(1, 'month').dueMonth
}

// --- When -------------------------------------------------------------------
// "In N units" drives the date. Shortcuts and the reason's configured
// default fill it in; picking a month or an exact day overrides it.
const intervalValue = ref<number | null>(1)
const intervalUnit = ref<RecallIntervalUnit>('month')
// Once the user sets the timing, changing the reason must not reset it.
const timingTouched = ref(false)
const showExactDate = ref(false)

// Settings are clinic-wide and rarely change; fetched once per modal.
let settingsRequest: Promise<RecallSettings | null> | null = null
const reasonDefaults = ref<RecallSettings | null>(null)

async function loadReasonDefaults() {
  settingsRequest ??= recallsApi.getSettings().then(res => res.data).catch(() => null)
  reasonDefaults.value = await settingsRequest
}

function applyInterval(value: number, unit: RecallIntervalUnit) {
  intervalValue.value = value
  intervalUnit.value = unit
  const timing = recallTimingFromInterval(value, unit)
  dueMonth.value = timing.dueMonth
  dueDate.value = timing.dueDate
  showExactDate.value = Boolean(timing.dueDate)
}

function applyReasonDefault() {
  if (timingTouched.value || props.initialDueMonth) return
  const value = reasonDefaults.value?.reason_intervals[reason.value]
  const unit = reasonDefaults.value?.reason_interval_units?.[reason.value] ?? 'month'
  if (typeof value === 'number' && isValidRecallInterval(value, unit)) applyInterval(value, unit)
  else applyInterval(1, 'month')
}

function chooseInterval(value: number, unit: RecallIntervalUnit) {
  timingTouched.value = true
  applyInterval(value, unit)
}

function onIntervalValueInput(raw: string | number | null | undefined) {
  timingTouched.value = true
  const value = raw === '' || raw === null || raw === undefined ? null : Number(raw)
  intervalValue.value = value
  if (value !== null && isValidRecallInterval(value, intervalUnit.value)) applyInterval(value, intervalUnit.value)
}

function onIntervalUnitChange(unit: RecallIntervalUnit) {
  timingTouched.value = true
  intervalUnit.value = unit
  const value = intervalValue.value
  if (value !== null && isValidRecallInterval(value, unit)) applyInterval(value, unit)
}

const intervalError = computed(() => {
  const value = intervalValue.value
  if (value === null || isValidRecallInterval(value, intervalUnit.value)) return undefined
  return t('recalls.modal.intervalRange', {
    max: RECALL_INTERVAL_MAX[intervalUnit.value],
    unit: t(`recalls.units.${intervalUnit.value}`)
  })
})

function onMonthPicked(month: string) {
  timingTouched.value = true
  intervalValue.value = null
  dueMonth.value = month
  // An exact day outside the chosen month would contradict it.
  if (dueDate.value && recallMonthOf(dueDate.value) !== month) dueDate.value = ''
}

function onExactDateInput(value: string | number | null | undefined) {
  timingTouched.value = true
  intervalValue.value = null
  dueDate.value = String(value ?? '')
  if (dueDate.value) dueMonth.value = recallMonthOf(dueDate.value)
}

watch(reason, applyReasonDefault)

watch(() => props.open, async (v) => {
  if (!v) return
  reason.value = props.initialReason
  priority.value = props.initialPriority
  timingTouched.value = false
  if (props.initialDueMonth) {
    intervalValue.value = null
    dueMonth.value = props.initialDueMonth
    dueDate.value = ''
    showExactDate.value = false
  } else {
    applyInterval(1, 'month')
  }
  note.value = props.initialNote ?? ''
  assignedProfessionalId.value = props.initialAssignedProfessionalId ?? null
  await loadReasonDefaults()
  applyReasonDefault()
}, { immediate: true })

interface ReasonMeta {
  value: RecallReason
  label: string
  icon: string
}

const reasons = computed<ReasonMeta[]>(() => [
  { value: 'hygiene', label: t('recalls.reasons.hygiene'), icon: 'i-lucide-sparkles' },
  { value: 'checkup', label: t('recalls.reasons.checkup'), icon: 'i-lucide-stethoscope' },
  { value: 'ortho_review', label: t('recalls.reasons.ortho_review'), icon: 'i-lucide-smile' },
  { value: 'implant_review', label: t('recalls.reasons.implant_review'), icon: 'i-lucide-anchor' },
  { value: 'post_op', label: t('recalls.reasons.post_op'), icon: 'i-lucide-bandage' },
  { value: 'treatment_followup', label: t('recalls.reasons.treatment_followup'), icon: 'i-lucide-clipboard-check' },
  { value: 'other', label: t('recalls.reasons.other'), icon: 'i-lucide-more-horizontal' }
])

const priorities = computed(() => [
  { value: 'low' as RecallPriority, label: t('recalls.priority.low'), color: 'neutral' as const },
  { value: 'normal' as RecallPriority, label: t('recalls.priority.normal'), color: 'info' as const },
  { value: 'high' as RecallPriority, label: t('recalls.priority.high'), color: 'error' as const }
])

const dueSummary = computed(() => {
  if (dueDate.value) {
    const d = new Date(`${dueDate.value}T00:00:00`)
    const label = new Intl.DateTimeFormat(locale.value, { dateStyle: 'full' }).format(d)
    return { prefix: t('recalls.modal.recallOn'), label }
  }
  const iso = dueMonth.value.length === 7 ? `${dueMonth.value}-01` : dueMonth.value
  const label = new Intl.DateTimeFormat(locale.value, { year: 'numeric', month: 'long' })
    .format(new Date(`${iso}T00:00:00`))
  return { prefix: t('recalls.modal.targetMonth'), label }
})

const shortcuts: { value: number, unit: RecallIntervalUnit }[] = [
  { value: 1, unit: 'week' },
  { value: 2, unit: 'week' },
  { value: 1, unit: 'month' },
  { value: 3, unit: 'month' },
  { value: 6, unit: 'month' },
  { value: 12, unit: 'month' }
]

function shortcutLabel(s: { value: number, unit: RecallIntervalUnit }): string {
  return t(`recalls.modal.shortcut.${s.unit}`, { n: s.value })
}

function isShortcutActive(s: { value: number, unit: RecallIntervalUnit }): boolean {
  return intervalValue.value === s.value && intervalUnit.value === s.unit
}

const unitOptions = computed(() =>
  RECALL_INTERVAL_UNITS.map(unit => ({ value: unit, label: t(`recalls.units.${unit}`) }))
)

async function save() {
  if (isSubmitting.value) return
  if (intervalError.value) {
    toast.add({ title: intervalError.value, color: 'warning' })
    return
  }
  isSubmitting.value = true
  try {
    const month = dueMonth.value || defaultDueMonth()
    const monthDay1 = month.length === 7 ? `${month}-01` : month
    const res = await recallsApi.create({
      patient_id: props.patientId,
      due_month: monthDay1,
      due_date: dueDate.value || null,
      reason: reason.value,
      reason_note: note.value || null,
      priority: priority.value,
      assigned_professional_id: assignedProfessionalId.value || null,
      linked_treatment_id: props.initialTreatmentId ?? null,
      linked_treatment_category_key: props.initialTreatmentCategoryKey ?? null
    })
    toast.add({ title: t('common.success'), color: 'success' })
    emit('saved', res.data)
    emit('update:open', false)
  } catch (err: unknown) {
    toast.add({
      title: t('common.error'),
      description: errorDetail(err),
      color: 'error'
    })
  } finally {
    isSubmitting.value = false
  }
}

function close() {
  emit('update:open', false)
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('recalls.modal.title')"
    :description="t('recalls.modal.subtitle')"
    :ui="{ content: 'sm:max-w-lg' }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-5 p-4 sm:p-5">
        <!-- Step 1: Reason — visual chips, primary thumb-friendly target -->
        <section>
          <label class="block text-caption uppercase tracking-wide text-subtle mb-2">
            {{ t('recalls.modal.reason') }}
          </label>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <button
              v-for="r in reasons"
              :key="r.value"
              type="button"
              :aria-pressed="reason === r.value"
              class="flex items-center gap-2 px-3 py-2 rounded-token-md border text-sm text-start transition-colors"
              :class="reason === r.value
                ? 'border-primary bg-primary/10 text-primary-accent'
                : 'border-default bg-default hover:bg-elevated text-default'"
              @click="reason = r.value"
            >
              <UIcon
                :name="r.icon"
                class="w-4 h-4 shrink-0"
              />
              <span class="truncate">{{ r.label }}</span>
            </button>
          </div>
        </section>

        <!-- Step 2: When — "in N units", shortcuts, or a month / exact day -->
        <section>
          <label class="block text-caption uppercase tracking-wide text-subtle mb-2">
            {{ t('recalls.modal.when') }}
          </label>
          <div
            class="flex flex-wrap items-center gap-2 mb-3"
            role="group"
            :aria-label="t('recalls.modal.shortcuts')"
          >
            <UButton
              v-for="s in shortcuts"
              :key="`${s.value}-${s.unit}`"
              size="xs"
              :color="isShortcutActive(s) ? 'primary' : 'neutral'"
              :variant="isShortcutActive(s) ? 'soft' : 'outline'"
              :aria-pressed="isShortcutActive(s)"
              @click="chooseInterval(s.value, s.unit)"
            >
              {{ shortcutLabel(s) }}
            </UButton>
          </div>

          <UFormField
            :label="t('recalls.modal.customInterval')"
            :error="intervalError"
          >
            <div class="flex gap-2">
              <UInput
                :model-value="intervalValue ?? undefined"
                type="number"
                inputmode="numeric"
                min="1"
                :max="RECALL_INTERVAL_MAX[intervalUnit]"
                step="1"
                class="w-24 shrink-0"
                :aria-label="t('recalls.modal.intervalValue')"
                @update:model-value="onIntervalValueInput"
              />
              <USelect
                :model-value="intervalUnit"
                :items="unitOptions"
                value-key="value"
                label-key="label"
                class="flex-1 min-w-0"
                :aria-label="t('recalls.modal.intervalUnit')"
                @update:model-value="(v) => onIntervalUnitChange(v as RecallIntervalUnit)"
              />
            </div>
          </UFormField>

          <div class="mt-3">
            <MonthPickerDropdown
              :model-value="dueMonth"
              @update:model-value="onMonthPicked"
            />
          </div>

          <p
            class="text-caption text-subtle mt-1.5"
            aria-live="polite"
          >
            {{ dueSummary.prefix }}: <span class="text-default font-medium">{{ dueSummary.label }}</span>
          </p>

          <details
            class="mt-3 group"
            :open="showExactDate"
            @toggle="showExactDate = ($event.target as HTMLDetailsElement).open"
          >
            <summary class="flex items-center gap-1 text-caption text-subtle cursor-pointer hover:text-default select-none">
              <UIcon
                name="i-lucide-chevron-right"
                class="w-3.5 h-3.5 transition-transform group-open:rotate-90"
              />
              {{ t('recalls.modal.preciseDate') }}
            </summary>
            <div class="mt-2">
              <UInput
                :model-value="dueDate"
                type="date"
                class="w-full"
                :aria-label="t('recalls.modal.preciseDate')"
                @update:model-value="onExactDateInput"
              />
            </div>
          </details>
        </section>

        <!-- Step 3: Priority — segmented control -->
        <section>
          <label class="block text-caption uppercase tracking-wide text-subtle mb-2">
            {{ t('recalls.modal.priority') }}
          </label>
          <div class="inline-flex rounded-token-md border border-default bg-default p-0.5 w-full">
            <button
              v-for="p in priorities"
              :key="p.value"
              type="button"
              class="flex-1 px-3 py-1.5 rounded text-sm font-medium transition-colors"
              :class="priority === p.value
                ? 'bg-primary/15 text-primary-accent'
                : 'text-subtle hover:text-default'"
              :aria-pressed="priority === p.value"
              @click="priority = p.value"
            >
              {{ p.label }}
            </button>
          </div>
        </section>

        <!-- Step 4: Note — optional context -->
        <section>
          <label class="block text-caption uppercase tracking-wide text-subtle mb-2">
            {{ t('recalls.modal.note') }}
            <span class="lowercase font-normal text-dimmed">· {{ t('recalls.modal.optional') }}</span>
          </label>
          <UTextarea
            v-model="note"
            :rows="3"
            :maxlength="500"
            :placeholder="t('recalls.modal.notePlaceholder')"
            class="w-full"
          />
          <p
            v-if="note.length > 400"
            class="text-caption text-dimmed mt-1 text-end tnum"
          >
            {{ note.length }} / 500
          </p>
        </section>
      </div>
    </template>
    <template #footer>
      <div class="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 p-3">
        <UButton
          color="neutral"
          variant="ghost"
          :disabled="isSubmitting"
          @click="close"
        >
          {{ t('actions.cancel') }}
        </UButton>
        <UButton
          color="primary"
          icon="i-lucide-bell"
          :loading="isSubmitting"
          @click="save"
        >
          {{ t('recalls.actions.save') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
