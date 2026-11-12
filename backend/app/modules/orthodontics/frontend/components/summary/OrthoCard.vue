<script setup lang="ts">
/**
 * Patient summary smart-card: the patient's open orthodontic case at a glance.
 * Registered in ``patient.summary.cards``; the slot host passes ``ctx``.
 */
import type { PatientExtended } from '~~/app/types'
import type { OrthoCase } from '../../composables/useOrthodontics'
import { orthoMonth } from '../../utils/orthoMonth'

interface Ctx {
  patient: PatientExtended
}

const props = defineProps<{ ctx: Ctx }>()

const { t } = useI18n()
const { listCases } = useOrthodontics()

const patientId = computed(() => props.ctx.patient.id)

const { data: active, status } = await useAsyncData<OrthoCase | null>(
  () => `orthodontics:summary-card:${patientId.value}`,
  async () => {
    try {
      const rows = await listCases({ patient_id: patientId.value })
      return rows.find(c => c.patient_id === patientId.value && (c.status === 'active' || c.status === 'paused')) ?? null
    } catch {
      return null
    }
  },
  { watch: [patientId], default: () => null, server: false }
)

const href = computed(() =>
  active.value ? `/orthodontics?case_id=${active.value.id}` : `/patients/${patientId.value}?tab=clinical`
)
</script>

<template>
  <SummaryCard
    :title="t('orthodontics.card.title')"
    icon="i-lucide-smile"
    severity="neutral"
    :loading="status === 'pending'"
    :empty="!active"
    :to="href"
  >
    <template #empty>
      {{ t('orthodontics.card.noCase') }}
    </template>

    <div
      v-if="active"
      class="space-y-1"
    >
      <p class="text-ui text-default">
        {{ t(`orthodontics.appliance.${active.appliance_type}`) }}
      </p>
      <p class="text-caption text-muted">
        {{ t(`orthodontics.status.${active.status}`) }}
        <span v-if="active.estimated_months">
          · {{ t('orthodontics.inbox.monthOf', { x: orthoMonth(active.start_date), n: active.estimated_months }) }}
        </span>
      </p>
    </div>
  </SummaryCard>
</template>
