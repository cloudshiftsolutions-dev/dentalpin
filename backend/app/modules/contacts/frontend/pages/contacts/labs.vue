<script setup lang="ts">
import { PERMISSIONS } from '~~/app/config/permissions'
import ContactDirectory from '../../components/ContactDirectory.vue'

definePageMeta({ middleware: ['auth'] })

const { can } = usePermissions()

if (!can(PERMISSIONS.contacts.read)) {
  await navigateTo('/')
}
</script>

<template>
  <ContactDirectory scope="labs" />
</template>
