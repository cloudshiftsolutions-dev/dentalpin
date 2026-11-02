<script setup lang="ts">
import type { PatientAddress } from '~~/app/types'
import { countryOptions as buildCountryOptions } from '~~/app/utils/countries'

/**
 * Home address block shared by the create and edit patient forms.
 * Writes into the ``patients.address`` JSONB shape.
 */
const address = defineModel<PatientAddress>({ required: true })

const { t, locale } = useI18n()

const countryOptions = computed(() => buildCountryOptions(locale.value))

function update(field: keyof PatientAddress, value: string | undefined) {
  address.value = { ...address.value, [field]: value ?? '' }
}
</script>

<template>
  <fieldset class="space-y-4">
    <legend class="text-body font-medium text-default mb-3">
      {{ t('patients.addressForm.title') }}
    </legend>

    <UFormField :label="t('patients.addressForm.street')">
      <UInput
        :model-value="address.street"
        autocomplete="street-address"
        maxlength="200"
        class="w-full"
        @update:model-value="update('street', $event as string)"
      />
    </UFormField>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <UFormField :label="t('patients.addressForm.city')">
        <UInput
          :model-value="address.city"
          autocomplete="address-level2"
          maxlength="100"
          class="w-full"
          @update:model-value="update('city', $event as string)"
        />
      </UFormField>
      <UFormField :label="t('patients.addressForm.postalCode')">
        <UInput
          :model-value="address.postal_code"
          autocomplete="postal-code"
          dir="ltr"
          maxlength="20"
          class="w-full"
          @update:model-value="update('postal_code', $event as string)"
        />
      </UFormField>
      <UFormField :label="t('patients.addressForm.province')">
        <UInput
          :model-value="address.province"
          autocomplete="address-level1"
          maxlength="100"
          class="w-full"
          @update:model-value="update('province', $event as string)"
        />
      </UFormField>
      <UFormField :label="t('patients.addressForm.country')">
        <USelectMenu
          :model-value="address.country"
          :items="countryOptions"
          value-key="value"
          label-key="label"
          searchable
          :search-input="{ placeholder: t('settings.countrySearchPlaceholder') }"
          :placeholder="t('settings.countryPlaceholder')"
          icon="i-lucide-globe"
          class="w-full"
          @update:model-value="update('country', $event as string)"
        />
      </UFormField>
    </div>
  </fieldset>
</template>
