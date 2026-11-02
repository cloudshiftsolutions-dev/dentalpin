<script setup lang="ts">
import { computeAge, dateOfBirthFromAge, MAX_PATIENT_AGE } from '../../../utils/medicalSnapshot'

/**
 * Date of birth + age, kept in sync. Age is not stored: typing it writes
 * an approximate ``date_of_birth`` (today's day/month, N years back) for
 * patients who don't know their exact birth date. ``ageInvalid`` lets the
 * parent block the save while the age box holds something unusable.
 */
interface Props {
  dobError?: string
}

defineProps<Props>()

const emit = defineEmits<{ blurDob: [] }>()

const dateOfBirth = defineModel<string>('dateOfBirth', { required: true })
const ageInvalid = defineModel<boolean>('ageInvalid', { default: false })

const { t } = useI18n()

const ageText = ref('')
const ageTouched = ref(false)

watch(dateOfBirth, (dob) => {
  const age = computeAge(dob)
  ageText.value = age === null || age < 0 ? '' : String(age)
  ageInvalid.value = false
}, { immediate: true })

function onAgeInput(value: string | number | null | undefined) {
  ageTouched.value = true
  const raw = String(value ?? '').trim()
  ageText.value = raw
  if (!raw) {
    ageInvalid.value = false
    dateOfBirth.value = ''
    return
  }
  const age = /^\d+$/.test(raw) ? Number(raw) : Number.NaN
  const dob = dateOfBirthFromAge(age)
  if (!dob) {
    ageInvalid.value = true
    return
  }
  ageInvalid.value = false
  // Keep an exact birth date that already matches the typed age.
  if (computeAge(dateOfBirth.value) !== age) dateOfBirth.value = dob
}

const ageError = computed(() =>
  ageInvalid.value && ageTouched.value
    ? t('patients.validation.age', { max: MAX_PATIENT_AGE })
    : undefined
)
</script>

<template>
  <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
    <UFormField
      :label="t('patients.dateOfBirth')"
      :error="dobError"
    >
      <UInput
        v-model="dateOfBirth"
        type="date"
        class="w-full"
        @blur="emit('blurDob')"
      />
    </UFormField>
    <UFormField
      :label="t('patients.age')"
      :hint="t('patients.ageUnit')"
      :help="ageError ? undefined : t('patients.ageHelp')"
      :error="ageError"
    >
      <UInput
        :model-value="ageText"
        type="number"
        inputmode="numeric"
        min="0"
        :max="MAX_PATIENT_AGE"
        step="1"
        class="w-full"
        @update:model-value="onAgeInput"
      />
    </UFormField>
  </div>
</template>
