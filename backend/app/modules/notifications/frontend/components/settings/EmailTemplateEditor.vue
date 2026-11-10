<script setup lang="ts">
import type { EmailTemplateDetail, EmailTemplatePreview } from '../../composables/useEmailTemplates'
import { errorDetail } from '~~/app/utils/error'

const props = defineProps<{
  templateKey: string
  templateLabel: string
  locale: string
  canEdit: boolean
}>()

const emit = defineEmits<{
  'dirty-change': [dirty: boolean]
  'saved': []
}>()

const { t, locale: uiLocale } = useI18n()
const toast = useToast()
const templates = useEmailTemplates()

const detail = ref<EmailTemplateDetail | null>(null)
const loading = ref(true)
const loadFailed = ref(false)

const subject = ref('')
const body = ref('')
const isActive = ref(true)

const saving = ref(false)
const sendingTest = ref(false)
const resetting = ref(false)
const showReset = ref(false)
const saveError = ref<string | null>(null)

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    applyDetail(await templates.get(props.templateKey, props.locale))
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

function applyDetail(value: EmailTemplateDetail) {
  detail.value = value
  subject.value = value.subject
  body.value = value.body_html
  isActive.value = value.is_active
  saveError.value = null
}

onMounted(load)

const isDirty = computed(() =>
  !!detail.value && (
    subject.value !== detail.value.subject
    || body.value !== detail.value.body_html
    || (detail.value.is_custom && isActive.value !== detail.value.is_active)
  )
)
watch(isDirty, value => emit('dirty-change', value), { immediate: true })
onBeforeUnmount(() => emit('dirty-change', false))

const status = computed<{ role: 'neutral' | 'success' | 'warning', label: string }>(() => {
  if (!detail.value?.is_custom) return { role: 'neutral', label: t('notifications.emailTemplates.status.default') }
  if (!detail.value.is_active) return { role: 'warning', label: t('notifications.emailTemplates.status.disabled') }
  return { role: 'success', label: t('notifications.emailTemplates.status.customised') }
})

const canSubmit = computed(() => subject.value.trim().length > 0 && body.value.trim().length > 0)

// ----- live preview ----------------------------------------------------

const preview = ref<EmailTemplatePreview | null>(null)
const previewError = ref<string | null>(null)
const previewLoading = ref(false)
let previewTimer: ReturnType<typeof setTimeout> | undefined
let previewSeq = 0

async function refreshPreview() {
  if (!canSubmit.value) return
  const seq = ++previewSeq
  previewLoading.value = true
  try {
    const result = await templates.preview(props.templateKey, props.locale, {
      subject: subject.value,
      body_html: body.value
    })
    if (seq !== previewSeq) return
    preview.value = result
    previewError.value = null
  } catch (e) {
    if (seq !== previewSeq) return
    previewError.value = errorDetail(e) ?? t('notifications.emailTemplates.editor.previewFailed')
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

watch([subject, body], () => {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(refreshPreview, 500)
})
watch(detail, (value) => {
  if (value) refreshPreview()
})
onBeforeUnmount(() => clearTimeout(previewTimer))

// ----- placeholders ----------------------------------------------------

const bodyField = ref<HTMLTextAreaElement | null>(null)
const subjectField = ref<{ inputRef?: HTMLInputElement | null } | null>(null)
const lastFocused = ref<'subject' | 'body'>('body')

function insertAt(current: string, el: HTMLInputElement | HTMLTextAreaElement | null | undefined, snippet: string) {
  const start = el?.selectionStart ?? current.length
  const end = el?.selectionEnd ?? current.length
  const next = current.slice(0, start) + snippet + current.slice(end)
  nextTick(() => {
    el?.focus()
    el?.setSelectionRange(start + snippet.length, start + snippet.length)
  })
  return next
}

function insertPlaceholder(snippet: string) {
  if (!props.canEdit) return
  if (lastFocused.value === 'subject' && !snippet.startsWith('{%')) {
    subject.value = insertAt(subject.value, subjectField.value?.inputRef, snippet)
  } else {
    body.value = insertAt(body.value, bodyField.value, snippet)
  }
}

// ----- actions ---------------------------------------------------------

async function save() {
  if (!canSubmit.value || saving.value) return
  saving.value = true
  saveError.value = null
  try {
    applyDetail(await templates.save(props.templateKey, props.locale, {
      subject: subject.value,
      body_html: body.value,
      is_active: isActive.value
    }))
    toast.add({ title: t('notifications.emailTemplates.editor.saved'), color: 'success' })
    emit('saved')
  } catch (e) {
    saveError.value = errorDetail(e) ?? t('notifications.emailTemplates.editor.saveFailed')
  } finally {
    saving.value = false
  }
}

async function sendTest() {
  if (!canSubmit.value || sendingTest.value) return
  sendingTest.value = true
  try {
    const email = await templates.sendTest(props.templateKey, props.locale, {
      subject: subject.value,
      body_html: body.value
    })
    toast.add({ title: t('notifications.emailTemplates.editor.testSent', { email }), color: 'success' })
  } catch (e) {
    toast.add({
      title: t('notifications.emailTemplates.editor.testFailed'),
      description: errorDetail(e),
      color: 'error'
    })
  } finally {
    sendingTest.value = false
  }
}

async function reset() {
  resetting.value = true
  try {
    applyDetail(await templates.reset(props.templateKey, props.locale))
    showReset.value = false
    toast.add({ title: t('notifications.emailTemplates.editor.resetDone'), color: 'success' })
    emit('saved')
  } catch (e) {
    toast.add({ title: t('notifications.emailTemplates.editor.resetFailed'), description: errorDetail(e), color: 'error' })
  } finally {
    resetting.value = false
  }
}

function discardChanges() {
  if (detail.value) applyDetail(detail.value)
}

function loadDefault() {
  if (!detail.value) return
  subject.value = detail.value.default_subject
  body.value = detail.value.default_body_html
}

const mobilePane = ref<'edit' | 'preview'>('edit')
const paneOptions = computed(() => [
  { value: 'edit', label: t('notifications.emailTemplates.editor.edit'), icon: 'i-lucide-code' },
  { value: 'preview', label: t('notifications.emailTemplates.editor.preview'), icon: 'i-lucide-eye' }
])

const bodyId = useId()
const lastSaved = computed(() =>
  detail.value?.updated_at
    ? new Intl.DateTimeFormat(uiLocale.value, { dateStyle: 'medium', timeStyle: 'short' })
        .format(new Date(detail.value.updated_at))
    : null
)
</script>

<template>
  <div class="space-y-4">
    <div
      v-if="loading"
      class="space-y-3"
    >
      <USkeleton class="h-16 w-full" />
      <USkeleton class="h-96 w-full" />
    </div>

    <SectionCard
      v-else-if="loadFailed || !detail"
      no-header
    >
      <EmptyState
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
    </SectionCard>

    <template v-else>
      <!-- Header: what is being edited + actions -->
      <SectionCard no-header>
        <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div class="min-w-0 space-y-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="text-h3 text-default">
                {{ templateLabel }}
              </h2>
              <StatusBadge
                :role="status.role"
                :label="status.label"
                size="xs"
              />
              <UBadge
                v-if="isDirty"
                color="warning"
                variant="soft"
                size="sm"
              >
                {{ t('notifications.emailTemplates.editor.unsaved') }}
              </UBadge>
            </div>
            <p class="text-caption text-subtle">
              {{ t(`notifications.emailTemplates.types.${templateKey}.description`) }}
              <template v-if="lastSaved">
                · {{ t('notifications.emailTemplates.editor.lastSaved', { date: lastSaved }) }}
              </template>
            </p>
          </div>

          <div
            v-if="canEdit"
            class="flex flex-wrap items-center gap-2 md:justify-end"
          >
            <UButton
              v-if="detail.is_custom"
              variant="ghost"
              color="error"
              icon="i-lucide-rotate-ccw"
              @click="showReset = true"
            >
              {{ t('notifications.emailTemplates.editor.reset') }}
            </UButton>
            <UButton
              v-if="isDirty"
              variant="ghost"
              color="neutral"
              @click="discardChanges"
            >
              {{ t('notifications.emailTemplates.editor.discard') }}
            </UButton>
            <UButton
              variant="outline"
              color="neutral"
              icon="i-lucide-send"
              :loading="sendingTest"
              :disabled="!canSubmit || !!previewError"
              @click="sendTest"
            >
              {{ t('notifications.emailTemplates.editor.sendTest') }}
            </UButton>
            <UButton
              color="primary"
              icon="i-lucide-save"
              :loading="saving"
              :disabled="!canSubmit || (!isDirty && detail.is_custom)"
              @click="save"
            >
              {{ t('notifications.emailTemplates.editor.save') }}
            </UButton>
          </div>
        </div>

        <UAlert
          v-if="saveError"
          class="mt-4"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('notifications.emailTemplates.editor.invalid')"
          :description="saveError"
        />

        <div
          v-if="canEdit"
          class="mt-4 flex items-start justify-between gap-4 rounded-token-md bg-surface-muted p-3"
        >
          <div>
            <p class="text-ui text-default">
              {{ t('notifications.emailTemplates.editor.active') }}
            </p>
            <p class="text-caption text-subtle">
              {{ t('notifications.emailTemplates.editor.activeHelp') }}
            </p>
          </div>
          <USwitch
            v-model="isActive"
            :aria-label="t('notifications.emailTemplates.editor.active')"
          />
        </div>
      </SectionCard>

      <div class="lg:hidden">
        <SegmentedControl
          :model-value="mobilePane"
          :options="paneOptions"
          full-width
          @update:model-value="mobilePane = $event as 'edit' | 'preview'"
        />
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <!-- Editor pane -->
        <SectionCard
          icon="i-lucide-code"
          :title="t('notifications.emailTemplates.editor.content')"
          :class="mobilePane === 'preview' ? 'hidden lg:block' : ''"
        >
          <div class="space-y-4">
            <UFormField
              :label="t('notifications.emailTemplates.editor.subject')"
              :help="t('notifications.emailTemplates.editor.subjectHelp')"
              required
            >
              <UInput
                ref="subjectField"
                v-model="subject"
                class="w-full"
                maxlength="255"
                :readonly="!canEdit"
                @focus="lastFocused = 'subject'"
              />
            </UFormField>

            <div
              v-if="canEdit"
              class="space-y-2"
            >
              <p class="text-ui text-default">
                {{ t('notifications.emailTemplates.editor.placeholders') }}
              </p>
              <div class="flex flex-wrap gap-1.5">
                <UTooltip
                  v-for="variable in detail.variables"
                  :key="variable.name"
                  :text="variable.snippet"
                >
                  <UButton
                    size="xs"
                    variant="soft"
                    color="neutral"
                    class="font-mono"
                    @mousedown.prevent
                    @click="insertPlaceholder(variable.snippet)"
                  >
                    {{ variable.name }}
                  </UButton>
                </UTooltip>
              </div>
              <p class="text-caption text-subtle">
                {{ t('notifications.emailTemplates.editor.placeholdersHelp') }}
              </p>
            </div>

            <div class="space-y-1.5">
              <div class="flex items-center justify-between gap-2">
                <label
                  :for="bodyId"
                  class="text-ui text-default"
                >
                  {{ t('notifications.emailTemplates.editor.html') }}
                </label>
                <UButton
                  v-if="canEdit && detail.is_custom"
                  size="xs"
                  variant="link"
                  color="neutral"
                  @click="loadDefault"
                >
                  {{ t('notifications.emailTemplates.editor.loadDefault') }}
                </UButton>
              </div>
              <textarea
                :id="bodyId"
                ref="bodyField"
                v-model="body"
                rows="28"
                spellcheck="false"
                autocapitalize="off"
                autocomplete="off"
                :readonly="!canEdit"
                class="block w-full resize-y rounded-token-md bg-(--color-surface) p-3 font-mono text-xs leading-5 text-default ring-1 ring-inset ring-[var(--color-border)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
                @focus="lastFocused = 'body'"
              />
              <p class="text-caption text-subtle">
                {{ t('notifications.emailTemplates.editor.htmlHelp') }}
              </p>
            </div>
          </div>
        </SectionCard>

        <!-- Preview pane -->
        <SectionCard
          icon="i-lucide-eye"
          :title="t('notifications.emailTemplates.editor.preview')"
          :class="mobilePane === 'edit' ? 'hidden lg:block' : ''"
        >
          <template #actions>
            <span
              v-if="previewLoading"
              class="inline-flex items-center gap-1.5 text-caption text-subtle"
              role="status"
            >
              <UIcon
                name="i-lucide-loader-circle"
                class="size-3.5 animate-spin motion-reduce:animate-none"
              />
              {{ t('notifications.emailTemplates.editor.previewUpdating') }}
            </span>
          </template>

          <div class="space-y-3">
            <p class="text-caption text-subtle">
              {{ t('notifications.emailTemplates.editor.previewHelp') }}
            </p>

            <UAlert
              v-if="previewError"
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="t('notifications.emailTemplates.editor.invalid')"
              :description="previewError"
            />

            <template v-if="preview">
              <div class="rounded-token-md bg-surface-muted px-3 py-2 text-ui">
                <span class="text-subtle">{{ t('notifications.emailTemplates.editor.previewSubject') }}</span>
                <span class="ml-1 text-default">{{ preview.subject }}</span>
              </div>
              <iframe
                :srcdoc="preview.html"
                sandbox=""
                referrerpolicy="no-referrer"
                :title="t('notifications.emailTemplates.editor.previewFrameTitle')"
                class="block h-160 w-full rounded-token-md bg-white ring-1 ring-[var(--color-border)]"
                :class="previewError ? 'opacity-60' : ''"
              />
            </template>
            <USkeleton
              v-else-if="!previewError"
              class="h-160 w-full"
            />
          </div>
        </SectionCard>
      </div>
    </template>

    <UModal v-model:open="showReset">
      <template #content>
        <UCard>
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon
                name="i-lucide-alert-triangle"
                class="w-5 h-5 text-danger-accent"
              />
              <h3 class="font-semibold text-default">
                {{ t('notifications.emailTemplates.editor.resetTitle') }}
              </h3>
            </div>
          </template>
          <p class="text-muted">
            {{ t('notifications.emailTemplates.editor.resetBody') }}
          </p>
          <div class="flex justify-end gap-2 pt-6">
            <UButton
              variant="ghost"
              @click="showReset = false"
            >
              {{ t('notifications.emailTemplates.editor.keepEditing') }}
            </UButton>
            <UButton
              color="error"
              :loading="resetting"
              @click="reset"
            >
              {{ t('notifications.emailTemplates.editor.reset') }}
            </UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
