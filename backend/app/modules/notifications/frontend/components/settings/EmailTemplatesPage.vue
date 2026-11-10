<script setup lang="ts">
import type { EmailTemplateSummary } from '../../composables/useEmailTemplates'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { can } = usePermissions()
const { list } = useEmailTemplates()
const { settings: communications, fetch: fetchCommunications } = useCommunicationsSettings()

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'ta', label: 'தமிழ்' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'pt', label: 'Português' },
  { value: 'de', label: 'Deutsch' },
  { value: 'it', label: 'Italiano' },
  { value: 'pl', label: 'Polski' },
  { value: 'hu', label: 'Magyar' },
  { value: 'ar', label: 'العربية' }
]
const LANGUAGE_CODES = LANGUAGES.map(l => l.value)

const canEdit = computed(() => can('notifications.templates.write'))

const summaries = ref<EmailTemplateSummary[]>([])
const loading = ref(true)
const loadFailed = ref(false)

const selectedKey = computed(() => (typeof route.query.template === 'string' ? route.query.template : null))
const language = computed(() => {
  const q = route.query.lang
  if (typeof q === 'string' && LANGUAGE_CODES.includes(q)) return q
  const clinicLang = communications.value?.language
  return clinicLang && LANGUAGE_CODES.includes(clinicLang) ? clinicLang : 'en'
})

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    summaries.value = await list()
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  fetchCommunications().catch(() => {})
})

function statusFor(summary: EmailTemplateSummary): { role: 'neutral' | 'success' | 'warning', label: string } {
  if (summary.customized_locales.includes(language.value)) {
    return { role: 'success', label: t('notifications.emailTemplates.status.customised') }
  }
  if (summary.disabled_locales.includes(language.value)) {
    return { role: 'warning', label: t('notifications.emailTemplates.status.disabled') }
  }
  return { role: 'neutral', label: t('notifications.emailTemplates.status.default') }
}

// ----- unsaved-changes guard -------------------------------------------

const editorDirty = ref(false)
const showDiscard = ref(false)
let resolveDiscard: ((ok: boolean) => void) | null = null

function confirmDiscard(): Promise<boolean> {
  if (!editorDirty.value) return Promise.resolve(true)
  showDiscard.value = true
  return new Promise((resolve) => {
    resolveDiscard = resolve
  })
}

function answerDiscard(ok: boolean) {
  showDiscard.value = false
  if (ok) editorDirty.value = false
  resolveDiscard?.(ok)
  resolveDiscard = null
}

watch(showDiscard, (open) => {
  if (!open && resolveDiscard) answerDiscard(false)
})

async function navigate(query: Record<string, string | undefined>) {
  if (!(await confirmDiscard())) return
  await router.replace({ query: { ...route.query, ...query } })
}

function openTemplate(key: string) {
  navigate({ template: key, lang: language.value })
}

function backToList() {
  navigate({ template: undefined })
}

function changeLanguage(value: string) {
  navigate({ lang: value })
}

onBeforeRouteLeave(() => confirmDiscard())

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!editorDirty.value) return
  event.preventDefault()
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

const selectedLabel = computed(() =>
  selectedKey.value ? t(`notifications.emailTemplates.types.${selectedKey.value}.label`) : ''
)
</script>

<template>
  <div class="space-y-4">
    <!-- Editor -->
    <template v-if="selectedKey">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <UButton
          variant="ghost"
          color="neutral"
          icon="i-lucide-arrow-left"
          @click="backToList"
        >
          {{ t('notifications.emailTemplates.editor.back') }}
        </UButton>
        <USelect
          :model-value="language"
          :items="LANGUAGES"
          :aria-label="t('notifications.emailTemplates.language')"
          icon="i-lucide-languages"
          class="w-44"
          @update:model-value="changeLanguage"
        />
      </div>

      <EmailTemplateEditor
        :key="`${selectedKey}:${language}`"
        :template-key="selectedKey"
        :template-label="selectedLabel"
        :locale="language"
        :can-edit="canEdit"
        @dirty-change="editorDirty = $event"
        @saved="load"
      />
    </template>

    <!-- List -->
    <SectionCard
      v-else
      icon="i-lucide-mail"
      :title="t('notifications.emailTemplates.listTitle')"
    >
      <template #actions>
        <USelect
          :model-value="language"
          :items="LANGUAGES"
          :aria-label="t('notifications.emailTemplates.language')"
          class="w-40"
          size="sm"
          @update:model-value="changeLanguage"
        />
      </template>

      <div class="space-y-4">
        <p class="text-body text-muted max-w-2xl">
          {{ t('notifications.emailTemplates.listHelp') }}
        </p>

        <UAlert
          v-if="!canEdit"
          color="info"
          variant="subtle"
          icon="i-lucide-eye"
          :title="t('notifications.emailTemplates.readOnly')"
        />

        <div
          v-if="loading"
          class="space-y-2"
        >
          <USkeleton
            v-for="i in 6"
            :key="i"
            class="h-12 w-full"
          />
        </div>

        <EmptyState
          v-else-if="loadFailed"
          icon="i-lucide-cloud-off"
          :title="t('notifications.emailTemplates.loadError')"
          :description="t('notifications.emailTemplates.loadErrorHelp')"
        >
          <template #actions>
            <UButton
              variant="soft"
              icon="i-lucide-refresh-cw"
              @click="load"
            >
              {{ t('notifications.emailTemplates.retry') }}
            </UButton>
          </template>
        </EmptyState>

        <ul
          v-else
          class="divide-y divide-[var(--color-border-subtle)]"
        >
          <li
            v-for="summary in summaries"
            :key="summary.template_key"
            class="py-1"
          >
            <ListRow
              clickable
              @click="openTemplate(summary.template_key)"
            >
              <template #leading>
                <UIcon
                  name="i-lucide-mail"
                  class="size-5 text-subtle"
                />
              </template>
              <template #title>
                {{ t(`notifications.emailTemplates.types.${summary.template_key}.label`) }}
              </template>
              <template #subtitle>
                {{ t(`notifications.emailTemplates.types.${summary.template_key}.description`) }}
              </template>
              <template #meta>
                <StatusBadge
                  :role="statusFor(summary).role"
                  :label="statusFor(summary).label"
                  size="xs"
                />
                <UIcon
                  name="i-lucide-chevron-right"
                  class="size-4 text-subtle"
                />
              </template>
            </ListRow>
          </li>
        </ul>

        <p class="text-caption text-subtle">
          {{ t('notifications.emailTemplates.whatsappNote') }}
        </p>
      </div>
    </SectionCard>

    <UModal v-model:open="showDiscard">
      <template #content>
        <UCard>
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon
                name="i-lucide-alert-triangle"
                class="w-5 h-5 text-warning-accent"
              />
              <h3 class="font-semibold text-default">
                {{ t('notifications.emailTemplates.editor.discardTitle') }}
              </h3>
            </div>
          </template>
          <p class="text-muted">
            {{ t('notifications.emailTemplates.editor.discardBody') }}
          </p>
          <div class="flex justify-end gap-2 pt-6">
            <UButton
              variant="ghost"
              @click="answerDiscard(false)"
            >
              {{ t('notifications.emailTemplates.editor.keepEditing') }}
            </UButton>
            <UButton
              color="error"
              @click="answerDiscard(true)"
            >
              {{ t('notifications.emailTemplates.editor.discard') }}
            </UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
