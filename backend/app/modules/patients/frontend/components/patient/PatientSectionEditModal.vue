<script setup lang="ts">
import type {
  PatientExtended,
  PatientExtendedUpdate,
  EmergencyContact,
  LegalGuardian,
  MedicalHistory,
  PatientAddress,
  PatientBillingAddress
} from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'
import {
  isValidDateOfBirth,
  isValidEmail,
  isValidPhone,
  PATIENT_PHONE_MAX_LENGTH
} from '~~/app/utils/contactValidation'
import { emptyPatientAddress, patientAddressPayload } from '../../utils/patientAddress'
import { buildGenderOptions, type PatientGender } from '../../utils/patientGender'

type SectionType = 'demographics' | 'emergency' | 'guardian' | 'billing' | 'medical'

interface Props {
  open: boolean
  section: SectionType
  patient: PatientExtended
  medicalHistory?: MedicalHistory
  isSavingMedical?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'save': [section: SectionType, data: Record<string, unknown>]
  'saveMedical': []
}>()

const { t } = useI18n()
const api = useApi()
const toast = useToast()

const isSubmitting = ref(false)

// Section titles
const sectionTitles: Record<SectionType, string> = {
  demographics: 'patients.editDemographics',
  emergency: 'patients.editEmergencyContact',
  guardian: 'patients.editLegalGuardian',
  billing: 'patients.editBilling',
  medical: 'patients.editMedicalHistory'
}

const modalTitle = computed(() => t(sectionTitles[props.section]))

// Form data for demographics
const demographicsForm = reactive({
  first_name: '',
  last_name: '',
  phone: '',
  email: '',
  date_of_birth: '',
  notes: '',
  do_not_contact: false as boolean,
  gender: undefined as PatientGender | undefined,
  national_id: '',
  national_id_type: undefined as string | undefined,
  profession: '',
  workplace: '',
  preferred_language: 'es',
  address: {
    street: '',
    city: '',
    postal_code: '',
    province: '',
    country: 'ES'
  } as PatientAddress
})

// Form data for emergency contact
const emergencyForm = ref<EmergencyContact | null>(null)

// Form data for legal guardian
const guardianForm = ref<LegalGuardian | null>(null)

// Form data for billing
const billingForm = reactive({
  billing_name: '',
  billing_tax_id: '',
  billing_email: '',
  billing_address: {
    street: '',
    city: '',
    postal_code: '',
    province: '',
    country: 'ES'
  } as PatientBillingAddress
})

const clinicCountry = useClinicCountry()

const genderOptions = computed(() => buildGenderOptions(t))

// Demographics validation: errors show on blur or after a save attempt.
type DemographicsField = 'phone' | 'email' | 'date_of_birth'
const submitted = ref(false)
const touched = ref<Partial<Record<DemographicsField, boolean>>>({})
const ageInvalid = ref(false)

const demographicsErrors = computed<Partial<Record<DemographicsField, string>>>(() => {
  const errors: Partial<Record<DemographicsField, string>> = {}
  if (!isValidPhone(demographicsForm.phone, { maxLength: PATIENT_PHONE_MAX_LENGTH })) {
    errors.phone = t('patients.validation.phone')
  }
  if (demographicsForm.email.trim() && !isValidEmail(demographicsForm.email)) {
    errors.email = t('patients.validation.email')
  }
  if (!isValidDateOfBirth(demographicsForm.date_of_birth)) {
    errors.date_of_birth = t('patients.validation.dateOfBirth')
  }
  return errors
})

function fieldError(field: DemographicsField): string | undefined {
  return submitted.value || touched.value[field] ? demographicsErrors.value[field] : undefined
}

function touch(field: DemographicsField) {
  touched.value = { ...touched.value, [field]: true }
}

// National ID type options
const nationalIdTypeOptions = computed(() => [
  { label: 'DNI', value: 'dni' },
  { label: 'NIE', value: 'nie' },
  { label: t('patients.passport'), value: 'passport' }
])

// Initialize form data when modal opens
watch(() => props.open, (isOpen) => {
  if (isOpen && props.patient) {
    initializeForm()
  }
}, { immediate: true })

function initializeForm() {
  if (props.section === 'demographics') {
    submitted.value = false
    touched.value = {}
    ageInvalid.value = false
    demographicsForm.first_name = props.patient.first_name
    demographicsForm.last_name = props.patient.last_name
    demographicsForm.phone = props.patient.phone || ''
    demographicsForm.email = props.patient.email || ''
    demographicsForm.date_of_birth = props.patient.date_of_birth || ''
    demographicsForm.notes = props.patient.notes || ''
    demographicsForm.do_not_contact = props.patient.do_not_contact ?? false
    demographicsForm.gender = props.patient.gender
    demographicsForm.national_id = props.patient.national_id || ''
    demographicsForm.national_id_type = props.patient.national_id_type
    demographicsForm.profession = props.patient.profession || ''
    demographicsForm.workplace = props.patient.workplace || ''
    demographicsForm.preferred_language = props.patient.preferred_language || 'es'
    demographicsForm.address = { ...emptyPatientAddress(clinicCountry.value), ...props.patient.address }
  } else if (props.section === 'emergency') {
    emergencyForm.value = props.patient.emergency_contact ? { ...props.patient.emergency_contact } : null
  } else if (props.section === 'guardian') {
    guardianForm.value = props.patient.legal_guardian ? { ...props.patient.legal_guardian } : null
  } else if (props.section === 'billing') {
    billingForm.billing_name = props.patient.billing_name || ''
    billingForm.billing_tax_id = props.patient.billing_tax_id || ''
    billingForm.billing_email = props.patient.billing_email || ''
    billingForm.billing_address = props.patient.billing_address || { street: '', city: '', postal_code: '', province: '', country: 'ES' }
  }
}

function closeModal() {
  emit('update:open', false)
}

async function handleSave() {
  if (props.section === 'medical') {
    emit('saveMedical')
    return
  }

  if (props.section === 'demographics') {
    submitted.value = true
    if (Object.keys(demographicsErrors.value).length || ageInvalid.value) {
      toast.add({ title: t('patients.validation.fixErrors'), color: 'warning' })
      return
    }
  }

  isSubmitting.value = true

  try {
    let updateData: Partial<PatientExtendedUpdate> | EmergencyContact | LegalGuardian | null = {}
    let endpoint = `/api/v1/patients/${props.patient.id}/extended`
    let method: 'put' | 'del' = 'put'

    if (props.section === 'demographics') {
      const address = patientAddressPayload(demographicsForm.address)
      updateData = {
        first_name: demographicsForm.first_name,
        last_name: demographicsForm.last_name,
        phone: demographicsForm.phone.trim() || null,
        email: demographicsForm.email.trim() || null,
        date_of_birth: demographicsForm.date_of_birth || null,
        notes: demographicsForm.notes || null,
        do_not_contact: demographicsForm.do_not_contact,
        gender: demographicsForm.gender || null,
        national_id: demographicsForm.national_id || null,
        national_id_type: demographicsForm.national_id_type || null,
        profession: demographicsForm.profession || null,
        workplace: demographicsForm.workplace || null,
        preferred_language: demographicsForm.preferred_language || 'es',
        address
      }
    } else if (props.section === 'emergency') {
      endpoint = `/api/v1/patients_clinical/patients/${props.patient.id}/emergency-contact`
      if (emergencyForm.value) {
        updateData = emergencyForm.value
      } else {
        method = 'del'
        updateData = null
      }
    } else if (props.section === 'guardian') {
      endpoint = `/api/v1/patients_clinical/patients/${props.patient.id}/legal-guardian`
      if (guardianForm.value) {
        updateData = guardianForm.value
      } else {
        method = 'del'
        updateData = null
      }
    } else if (props.section === 'billing') {
      const billingAddress = billingForm.billing_address?.street ? billingForm.billing_address : null
      updateData = {
        billing_name: billingForm.billing_name || null,
        billing_tax_id: billingForm.billing_tax_id || null,
        billing_email: billingForm.billing_email || null,
        billing_address: billingAddress
      }
    }

    if (method === 'del') {
      try {
        await api.del(endpoint, { errorToast: false })
      } catch (e: unknown) {
        // Emergency/guardian may not exist yet — delete 404 is harmless.
        const err = e as { statusCode?: number }
        if (err.statusCode !== 404) throw e
      }
    } else {
      // Failures are toasted by the catch below — keep single-toast.
      await api.put(endpoint, updateData as Record<string, unknown>, { errorToast: false })
    }

    toast.add({
      title: t('common.success'),
      description: t('patients.updated'),
      color: 'success'
    })

    closeModal()
    // Emit after close to avoid reactive loop during refresh
    await nextTick()
    emit('save', props.section, (updateData ?? {}) as Record<string, unknown>)
  } catch (error: unknown) {
    toast.add({
      title: t('common.error'),
      description: errorMessage(error, t('common.serverError')),
      color: 'error'
    })
  } finally {
    isSubmitting.value = false
  }
}

const canSave = computed(() => {
  if (props.section === 'demographics') {
    return Boolean(demographicsForm.first_name.trim() && demographicsForm.last_name.trim())
  }
  return true
})
</script>

<template>
  <UModal
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <UCard :ui="{ root: 'w-full max-w-2xl', body: 'overflow-visible' }">
        <template #header>
          <div class="flex items-center justify-between">
            <h2 class="text-h1 text-default">
              {{ modalTitle }}
            </h2>
            <UButton
              variant="ghost"
              color="neutral"
              icon="i-lucide-x"
              size="sm"
              :aria-label="t('common.close', 'Cerrar')"
              @click="closeModal"
            />
          </div>
        </template>

        <!-- Demographics Form -->
        <div
          v-if="section === 'demographics'"
          class="space-y-4 max-h-[65vh] overflow-y-auto pe-1"
        >
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <UFormField
              :label="t('patients.firstName')"
              required
            >
              <UInput
                v-model="demographicsForm.first_name"
                required
              />
            </UFormField>
            <UFormField
              :label="t('patients.lastName')"
              required
            >
              <UInput
                v-model="demographicsForm.last_name"
                required
              />
            </UFormField>
            <UFormField
              :label="t('patients.phone')"
              :error="fieldError('phone')"
            >
              <UInput
                v-model="demographicsForm.phone"
                type="tel"
                inputmode="tel"
                autocomplete="tel"
                dir="ltr"
                :maxlength="PATIENT_PHONE_MAX_LENGTH"
                class="w-full"
                @blur="touch('phone')"
              />
            </UFormField>
            <UFormField
              :label="t('patients.email')"
              :error="fieldError('email')"
            >
              <UInput
                v-model="demographicsForm.email"
                type="email"
                autocomplete="email"
                dir="ltr"
                maxlength="254"
                class="w-full"
                @blur="touch('email')"
              />
            </UFormField>
            <PatientBirthAgeFields
              v-model:date-of-birth="demographicsForm.date_of_birth"
              v-model:age-invalid="ageInvalid"
              :dob-error="fieldError('date_of_birth')"
              class="md:col-span-2"
              @blur-dob="touch('date_of_birth')"
            />
            <UFormField :label="t('patients.gender.label')">
              <USelect
                v-model="demographicsForm.gender"
                :items="genderOptions"
                value-key="value"
                label-key="label"
                :placeholder="t('patients.gender.select')"
              />
            </UFormField>
            <UFormField :label="t('patients.nationalIdType')">
              <USelect
                v-model="demographicsForm.national_id_type"
                :items="nationalIdTypeOptions"
                value-key="value"
                label-key="label"
              />
            </UFormField>
            <UFormField :label="t('patients.nationalId')">
              <UInput v-model="demographicsForm.national_id" />
            </UFormField>
            <UFormField :label="t('patients.profession')">
              <UInput v-model="demographicsForm.profession" />
            </UFormField>
            <UFormField :label="t('patients.workplace')">
              <UInput v-model="demographicsForm.workplace" />
            </UFormField>
          </div>
          <PatientAddressFields v-model="demographicsForm.address" />
          <UFormField :label="t('patients.notes')">
            <UTextarea
              v-model="demographicsForm.notes"
              :rows="3"
            />
          </UFormField>
          <UFormField
            :label="t('patients.doNotContact.label')"
            :hint="t('patients.doNotContact.hint')"
          >
            <USwitch v-model="demographicsForm.do_not_contact" />
          </UFormField>
        </div>

        <!-- Emergency Contact Form -->
        <div
          v-else-if="section === 'emergency'"
          class="space-y-4 max-h-[65vh] overflow-y-auto pe-1"
        >
          <EmergencyContactForm v-model="emergencyForm" />
        </div>

        <!-- Legal Guardian Form -->
        <div
          v-else-if="section === 'guardian'"
          class="space-y-4 max-h-[65vh] overflow-y-auto pe-1"
        >
          <LegalGuardianForm v-model="guardianForm" />
        </div>

        <!-- Billing Form -->
        <div
          v-else-if="section === 'billing'"
          class="space-y-4 max-h-[65vh] overflow-y-auto pe-1"
        >
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <UFormField :label="t('patients.billingName')">
              <UInput
                v-model="billingForm.billing_name"
                :placeholder="t('patients.billingNamePlaceholder')"
              />
            </UFormField>
            <UFormField :label="t('patients.billingTaxId')">
              <UInput
                v-model="billingForm.billing_tax_id"
                placeholder="NIF/CIF"
              />
            </UFormField>
            <UFormField :label="t('patients.billingEmail')">
              <UInput
                v-model="billingForm.billing_email"
                type="email"
              />
            </UFormField>
          </div>
          <div class="mt-4">
            <h4 class="text-sm font-medium text-muted mb-3">
              {{ t('patients.billingAddress') }}
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="md:col-span-2">
                <UFormField :label="t('invoice.street')">
                  <UInput v-model="billingForm.billing_address.street" />
                </UFormField>
              </div>
              <UFormField :label="t('invoice.city')">
                <UInput v-model="billingForm.billing_address.city" />
              </UFormField>
              <UFormField :label="t('invoice.postalCode')">
                <UInput v-model="billingForm.billing_address.postal_code" />
              </UFormField>
              <UFormField :label="t('invoice.province')">
                <UInput v-model="billingForm.billing_address.province" />
              </UFormField>
              <UFormField :label="t('invoice.country')">
                <UInput v-model="billingForm.billing_address.country" />
              </UFormField>
            </div>
          </div>
        </div>

        <!-- Medical History Form -->
        <div
          v-else-if="section === 'medical'"
          class="max-h-[65vh] overflow-y-auto pe-1"
        >
          <MedicalHistoryForm
            v-if="medicalHistory"
            :model-value="medicalHistory"
            hide-actions
          />
        </div>

        <template #footer>
          <div class="flex justify-end gap-3">
            <UButton
              variant="outline"
              color="neutral"
              @click="closeModal"
            >
              {{ t('common.cancel') }}
            </UButton>
            <UButton
              :loading="isSubmitting || isSavingMedical"
              :disabled="!canSave"
              @click="handleSave"
            >
              {{ t('common.save') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
