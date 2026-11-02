<script setup lang="ts">
import type { Patient, PatientAddress, PatientCreate, PaginatedResponse, ApiResponse } from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'
import {
  isValidDateOfBirth,
  isValidEmail,
  isValidPhone,
  PATIENT_PHONE_MAX_LENGTH
} from '~~/app/utils/contactValidation'
import { PATIENT_STATUS_ROLE, type PatientStatus } from '~~/app/config/severity'
import { PERMISSIONS } from '~~/app/config/permissions'
import { emptyPatientAddress, patientAddressPayload } from '../../utils/patientAddress'
import { buildGenderOptions, type PatientGender } from '../../utils/patientGender'

/**
 * /patients — list page.
 *
 * Filter + enrichment design:
 *   - Native filters (status, city, do_not_contact, search, sort) hit
 *     ``GET /api/v1/patients`` directly.
 *   - Cross-module enrichment (debt, on-account credit) is rendered via
 *     the ``patients.list.row.financial`` slot. Payments registers the
 *     slot filler. The page fetches the payment summary in bulk after
 *     the patient page loads and passes it into each slot's ctx.
 *   - Cross-module filter "Con deuda" uses ``patients.list.filter``
 *     slot. The page translates the filter into a payments-side call
 *     (``/api/v1/payments/filters/patients-with-debt``) returning the
 *     patient_ids set, which is then intersected with /patients via
 *     ``?patient_ids=`` query params.
 *
 * Patients module never imports payments code — both calls go through
 * ``useApi()`` against the public HTTP surface.
 */

interface PatientDebtSummary {
  total_paid: string
  debt: string
  on_account_balance: string
}

const { t } = useI18n()
const api = useApi()
const toast = useToast()
const router = useRouter()
const route = useRoute()
const { can } = usePermissions()

// --- Filter shape (URL-synced) ------------------------------------------
interface PatientListFilters {
  q: string
  status: string[]
  city: string
  do_not_contact: boolean | null
  with_debt: boolean
}

const defaults: PatientListFilters = {
  q: '',
  status: ['active'],
  city: '',
  do_not_contact: null,
  with_debt: false
}

// Map of patient_id → payment summary; filled after each page load and
// passed into the slot via ctx.
const debtSummaries = ref<Record<string, PatientDebtSummary | null>>({})

async function fetcher(q: {
  filters: PatientListFilters
  page: number
  pageSize: number
  sort: string
}) {
  // Step 1: when "with_debt" is on, resolve the candidate ids through
  // the payments-side filter endpoint. Public HTTP — no code-level
  // dependency on the payments module.
  let patientIdsIntersect: string[] | undefined
  if (q.filters.with_debt) {
    try {
      const res = await api.get<ApiResponse<{ patient_ids: string[], truncated: boolean }>>(
        '/api/v1/payments/filters/patients-with-debt?min_debt=0.01'
      )
      patientIdsIntersect = res.data.patient_ids ?? []
      if (res.data.truncated) {
        toast.add({ title: t('lists.truncatedWarning'), color: 'warning' })
      }
      if (!patientIdsIntersect.length) {
        debtSummaries.value = {}
        return { data: [], total: 0 }
      }
    } catch {
      // Permission denied or payments uninstalled → ignore the filter.
      patientIdsIntersect = undefined
    }
  }

  // Step 2: query /patients with the optional intersect + native filters.
  const params = new URLSearchParams()
  params.set('page', String(q.page))
  params.set('page_size', String(q.pageSize))
  if (q.filters.q) params.set('search', q.filters.q)
  if (q.filters.city) params.set('city', q.filters.city)
  if (q.filters.do_not_contact !== null) {
    params.set('do_not_contact', q.filters.do_not_contact ? 'true' : 'false')
  }
  // The chips map straight onto the API's ``status`` filter, so picking
  // "Archived" alone returns archived patients alone (#473). An empty
  // selection means "no status restriction" and needs ``include_archived``,
  // because with no status list the API still hides archived rows.
  if (q.filters.status.length) {
    for (const value of q.filters.status) params.append('status', value)
  } else {
    params.set('include_archived', 'true')
  }
  if (patientIdsIntersect) {
    for (const id of patientIdsIntersect) params.append('patient_ids', id)
  }
  if (q.sort) params.set('sort', q.sort)

  const response = await api.get<PaginatedResponse<Patient>>(`/api/v1/patients?${params.toString()}`)

  // Step 3: bulk-fetch payment summaries for the page rows (when the
  // user has permission). The slot renders nothing for ids missing
  // from the map.
  if (can(PERMISSIONS.payments.recordRead) && response.data.length) {
    try {
      const summaryRes = await api.post<ApiResponse<{ summaries: Record<string, PatientDebtSummary> }>>(
        '/api/v1/payments/summary/by-patients',
        { patient_ids: response.data.map(x => x.id) }
      )
      debtSummaries.value = summaryRes.data.summaries
    } catch {
      debtSummaries.value = {}
    }
  } else {
    debtSummaries.value = {}
  }

  return { data: response.data, total: response.total }
}

const {
  filters,
  page,
  pageSize,
  sort,
  rows: patients,
  total,
  totalPages,
  isLoading,
  error,
  setFilter,
  resetFilters,
  refresh
} = useListQuery<PatientListFilters, Patient>({
  defaults,
  pageSize: 20,
  sortable: ['last_visit', 'last_name', 'first_name', 'created_at', 'updated_at'],
  defaultSort: 'last_visit:desc',
  searchKey: 'q',
  fetcher
})

const statusItems = computed(() => [
  { label: t('patients.status.active'), value: 'active' },
  { label: t('patients.status.archived'), value: 'archived' }
])

const sortOptions = computed(() => [
  { field: 'last_visit', label: t('patients.sort.lastVisit'), defaultDir: 'desc' as const },
  { field: 'last_name', label: t('patients.sort.lastName'), defaultDir: 'asc' as const },
  { field: 'first_name', label: t('patients.sort.firstName'), defaultDir: 'asc' as const },
  { field: 'created_at', label: t('patients.sort.createdAt'), defaultDir: 'desc' as const },
  { field: 'updated_at', label: t('patients.sort.updatedAt'), defaultDir: 'desc' as const }
])

const activeFilterCount = computed(() => {
  let n = 0
  // Any selection other than the default changes the result set —
  // including the empty one, which now widens it to archived patients
  // too, so it has to count as a filter rather than read as "none".
  if (filters.value.status.join(',') !== 'active') n++
  if (filters.value.city) n++
  if (filters.value.do_not_contact !== null) n++
  if (filters.value.with_debt) n++
  return n
})

function debtFilterCtx() {
  return {
    value: filters.value.with_debt,
    onChange: (v: boolean | null) => setFilter('with_debt', Boolean(v))
  }
}

// --- Create modal --------------------------------------------------------
const isCreateModalOpen = ref(false)
const isSubmitting = ref(false)
const clinicCountry = useClinicCountry()

interface NewPatientForm {
  first_name: string
  last_name: string
  phone: string
  email: string
  national_id: string
  date_of_birth: string
  gender: PatientGender | undefined
  address: PatientAddress
  notes: string
}

function blankForm(): NewPatientForm {
  return {
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
    national_id: '',
    date_of_birth: '',
    gender: undefined,
    address: emptyPatientAddress(clinicCountry.value),
    notes: ''
  }
}

const newPatient = reactive<NewPatientForm>(blankForm())
const ageInvalid = ref(false)

const genderOptions = computed(() => buildGenderOptions(t))

onMounted(() => {
  if (route.query.new === '1') {
    isCreateModalOpen.value = true
    router.replace({ query: { ...route.query, new: undefined } })
  }
})

function resetForm() {
  Object.assign(newPatient, blankForm())
  ageInvalid.value = false
  submitted.value = false
  touched.value = {}
}

// Errors surface on blur or after a save attempt, so an empty form does
// not open covered in red.
type CreateField = 'first_name' | 'last_name' | 'phone' | 'email' | 'date_of_birth'
const submitted = ref(false)
const touched = ref<Partial<Record<CreateField, boolean>>>({})

const createErrors = computed<Partial<Record<CreateField, string>>>(() => {
  const errors: Partial<Record<CreateField, string>> = {}
  if (!newPatient.first_name.trim()) errors.first_name = t('patients.validation.firstName')
  if (!newPatient.last_name.trim()) errors.last_name = t('patients.validation.lastName')
  if (!isValidPhone(newPatient.phone, { maxLength: PATIENT_PHONE_MAX_LENGTH })) {
    errors.phone = t('patients.validation.phone')
  }
  if (newPatient.email.trim() && !isValidEmail(newPatient.email)) {
    errors.email = t('patients.validation.email')
  }
  if (!isValidDateOfBirth(newPatient.date_of_birth)) {
    errors.date_of_birth = t('patients.validation.dateOfBirth')
  }
  return errors
})

watch(isCreateModalOpen, (open) => {
  if (!open) return
  submitted.value = false
  touched.value = {}
  // The clinic may load after this page; fill the country once it does.
  const hasAddress = patientAddressPayload(newPatient.address) !== null
  if (!hasAddress && clinicCountry.value) newPatient.address.country = clinicCountry.value
})

function fieldError(field: CreateField): string | undefined {
  return submitted.value || touched.value[field] ? createErrors.value[field] : undefined
}

function touch(field: CreateField) {
  touched.value = { ...touched.value, [field]: true }
}

async function createPatient() {
  submitted.value = true
  if (Object.keys(createErrors.value).length || ageInvalid.value) {
    toast.add({ title: t('patients.validation.fixErrors'), color: 'warning' })
    return
  }

  isSubmitting.value = true
  try {
    const payload: PatientCreate = {
      first_name: newPatient.first_name.trim(),
      last_name: newPatient.last_name.trim(),
      phone: newPatient.phone.trim() || undefined,
      email: newPatient.email.trim() || undefined,
      national_id: newPatient.national_id.trim() || undefined,
      date_of_birth: newPatient.date_of_birth || undefined,
      gender: newPatient.gender,
      address: patientAddressPayload(newPatient.address) ?? undefined,
      notes: newPatient.notes.trim() || undefined
    }
    const response = await api.post<ApiResponse<Patient>>('/api/v1/patients', payload, { errorToast: false })
    toast.add({
      title: t('common.success'),
      description: t('patients.created'),
      color: 'success'
    })
    isCreateModalOpen.value = false
    resetForm()
    await refresh()
    await router.push(`/patients/${response.data.id}`)
  } catch (e: unknown) {
    toast.add({
      title: t('common.error'),
      description: errorMessage(e, t('common.serverError')),
      color: 'error'
    })
  } finally {
    isSubmitting.value = false
  }
}

function patientCity(p: Patient): string {
  const addr = (p as Patient & { address?: { city?: string } }).address
  return addr?.city || ''
}
</script>

<template>
  <div>
    <DataListLayout
      :title="t('patients.title')"
      :loading="isLoading"
      :empty="!patients.length"
      :error="error"
      :page="page"
      :page-size="pageSize"
      :total="total"
      :total-pages="totalPages"
      @update:page="(v) => (page = v)"
    >
      <template #actions>
        <UButton
          color="primary"
          variant="soft"
          icon="i-lucide-plus"
          @click="isCreateModalOpen = true"
        >
          {{ t('patients.create') }}
        </UButton>
      </template>

      <template #toolbar>
        <FilterBar
          :active-count="activeFilterCount"
          @reset="resetFilters"
        >
          <template #search>
            <SearchBar
              :model-value="filters.q"
              :placeholder="t('patients.searchPlaceholder')"
              max-width="max-w-md"
              @update:model-value="(v) => setFilter('q', v)"
            />
          </template>

          <FilterChipMulti
            :model-value="filters.status"
            :items="statusItems"
            :label="t('patients.filters.status')"
            icon="i-lucide-circle-dot"
            @update:model-value="(v) => setFilter('status', v)"
          />

          <FilterToggle
            :model-value="filters.do_not_contact"
            :label="t('patients.filters.doNotContactOnly')"
            :label-false="t('patients.filters.doNotContactOnlyContactable')"
            icon="i-lucide-bell-off"
            tristate
            @update:model-value="(v) => setFilter('do_not_contact', v)"
          />

          <ModuleSlot
            name="patients.list.filter"
            :ctx="debtFilterCtx()"
          />

          <template #right>
            <SortMenu
              :model-value="sort"
              :options="sortOptions"
              @update:model-value="(v) => (sort = v)"
            />
          </template>
        </FilterBar>
      </template>

      <template #empty>
        <EmptyState
          icon="i-lucide-users"
          :title="activeFilterCount || filters.q ? t('patients.noResults') : t('patients.empty')"
          :description="activeFilterCount || filters.q ? undefined : t('dashboard.welcomeMessage')"
        >
          <template
            v-if="!activeFilterCount && !filters.q"
            #actions
          >
            <UButton
              color="primary"
              variant="soft"
              icon="i-lucide-plus"
              @click="isCreateModalOpen = true"
            >
              {{ t('patients.emptyAction') }}
            </UButton>
          </template>
        </EmptyState>
      </template>

      <template #rows>
        <DataListItem
          v-for="patient in patients"
          :key="patient.id"
          :to="`/patients/${patient.id}`"
        >
          <template #row>
            <UAvatar
              :alt="patient.first_name"
              size="sm"
            />
            <div class="flex-1 min-w-0">
              <div class="text-ui text-default truncate flex items-center gap-2">
                {{ patient.last_name }}, {{ patient.first_name }}
                <UIcon
                  v-if="patient.do_not_contact"
                  name="i-lucide-bell-off"
                  class="w-3.5 h-3.5 text-warning shrink-0"
                  :title="t('patients.doNotContact.label')"
                />
              </div>
              <div class="text-caption text-subtle truncate">
                <span v-if="patientCity(patient)">{{ patientCity(patient) }} · </span><span dir="ltr">{{ patient.phone || patient.email || '—' }}</span>
              </div>
            </div>
            <div class="shrink-0 flex items-center gap-3 ms-auto">
              <ModuleSlot
                name="patients.list.row.financial"
                :ctx="{ patient_id: patient.id, summary: debtSummaries[patient.id] ?? null }"
              />
              <StatusBadge
                :role="PATIENT_STATUS_ROLE[patient.status as PatientStatus] || 'neutral'"
                :label="t(`patients.status.${patient.status}`)"
              />
              <UIcon
                name="i-lucide-chevron-right"
                class="text-subtle"
              />
            </div>
          </template>

          <template #card>
            <div class="flex items-center gap-3">
              <UAvatar
                :alt="patient.first_name"
                size="md"
              />
              <div class="flex-1 min-w-0">
                <div class="font-medium text-default truncate flex items-center gap-2">
                  {{ patient.last_name }}, {{ patient.first_name }}
                  <UIcon
                    v-if="patient.do_not_contact"
                    name="i-lucide-bell-off"
                    class="w-3.5 h-3.5 text-warning shrink-0"
                  />
                </div>
                <div class="text-caption text-subtle truncate">
                  <span dir="ltr">{{ patient.phone || patient.email || '—' }}</span>
                </div>
              </div>
              <StatusBadge
                :role="PATIENT_STATUS_ROLE[patient.status as PatientStatus] || 'neutral'"
                :label="t(`patients.status.${patient.status}`)"
                class="shrink-0"
              />
            </div>
            <div class="flex items-center justify-between gap-2">
              <span class="text-caption text-subtle truncate">
                {{ patientCity(patient) || '—' }}
              </span>
              <ModuleSlot
                name="patients.list.row.financial"
                :ctx="{ patient_id: patient.id, summary: debtSummaries[patient.id] ?? null }"
              />
            </div>
          </template>
        </DataListItem>
      </template>
    </DataListLayout>

    <UModal v-model:open="isCreateModalOpen">
      <template #content>
        <UCard :ui="{ root: 'w-full max-w-2xl', body: 'overflow-visible' }">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-h1 text-default">
                {{ t('patients.create') }}
              </h2>
              <UButton
                variant="ghost"
                color="neutral"
                icon="i-lucide-x"
                :aria-label="t('common.close', 'Cerrar')"
                @click="isCreateModalOpen = false"
              />
            </div>
          </template>

          <form
            id="create-patient-form"
            class="space-y-4 max-h-[65vh] overflow-y-auto pe-1"
            novalidate
            @submit.prevent="createPatient"
          >
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <UFormField
                :label="t('patients.firstName')"
                :error="fieldError('first_name')"
                required
              >
                <UInput
                  v-model="newPatient.first_name"
                  autocomplete="given-name"
                  maxlength="100"
                  class="w-full"
                  @blur="touch('first_name')"
                />
              </UFormField>
              <UFormField
                :label="t('patients.lastName')"
                :error="fieldError('last_name')"
                required
              >
                <UInput
                  v-model="newPatient.last_name"
                  autocomplete="family-name"
                  maxlength="100"
                  class="w-full"
                  @blur="touch('last_name')"
                />
              </UFormField>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <UFormField
                :label="t('patients.phone')"
                :error="fieldError('phone')"
              >
                <UInput
                  v-model="newPatient.phone"
                  type="tel"
                  inputmode="tel"
                  autocomplete="tel"
                  dir="ltr"
                  :maxlength="PATIENT_PHONE_MAX_LENGTH"
                  placeholder="+91 98765 43210"
                  class="w-full"
                  @blur="touch('phone')"
                />
              </UFormField>
              <UFormField
                :label="t('patients.email')"
                :error="fieldError('email')"
              >
                <UInput
                  v-model="newPatient.email"
                  type="email"
                  autocomplete="email"
                  dir="ltr"
                  maxlength="254"
                  class="w-full"
                  @blur="touch('email')"
                />
              </UFormField>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <UFormField :label="t('patients.gender.label')">
                <USelect
                  v-model="newPatient.gender"
                  :items="genderOptions"
                  value-key="value"
                  label-key="label"
                  :placeholder="t('patients.gender.select')"
                  class="w-full"
                />
              </UFormField>
              <UFormField :label="t('patients.nationalId')">
                <UInput
                  v-model="newPatient.national_id"
                  maxlength="50"
                  class="w-full"
                />
              </UFormField>
            </div>

            <PatientBirthAgeFields
              v-model:date-of-birth="newPatient.date_of_birth"
              v-model:age-invalid="ageInvalid"
              :dob-error="fieldError('date_of_birth')"
              @blur-dob="touch('date_of_birth')"
            />

            <PatientAddressFields v-model="newPatient.address" />

            <UFormField :label="t('patients.notes')">
              <UTextarea
                v-model="newPatient.notes"
                :rows="3"
                class="w-full"
              />
            </UFormField>
          </form>

          <template #footer>
            <div class="flex justify-end gap-3">
              <UButton
                variant="outline"
                color="neutral"
                @click="isCreateModalOpen = false"
              >
                {{ t('common.cancel') }}
              </UButton>
              <UButton
                type="submit"
                form="create-patient-form"
                color="primary"
                variant="solid"
                :loading="isSubmitting"
              >
                {{ t('patients.createAction') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
