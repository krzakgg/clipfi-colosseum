<script setup>
import { nextTick, ref, watch } from 'vue'
import { uploadImages } from '../utils/uploadImage'

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, required: true },
  placeholder: { type: String, default: 'Enter details...' },
  minHeight: { type: String, default: '150px' }
})

const emit = defineEmits(['update:modelValue'])
const editor = ref(null)
const imageInput = ref(null)
const uploadingImage = ref(false)

const sanitizeContent = (value) => {
  const documentParser = new DOMParser()
  const parsed = documentParser.parseFromString(value || '', 'text/html')
  const allowedTags = new Set(['A', 'B', 'BR', 'EM', 'H1', 'H2', 'H3', 'IMG', 'I', 'LI', 'OL', 'P', 'STRONG', 'U', 'UL'])

  parsed.body.querySelectorAll('*').forEach(element => {
    if (!allowedTags.has(element.tagName)) {
      element.replaceWith(...element.childNodes)
      return
    }

    Array.from(element.attributes).forEach(attribute => {
      if (!['alt', 'href', 'src', 'target'].includes(attribute.name)) element.removeAttribute(attribute.name)
    })

    if (element.tagName === 'A' && !/^https?:\/\//i.test(element.getAttribute('href') || '')) element.removeAttribute('href')
    if (element.tagName === 'IMG' && !/^(https?:\/\/|data:image\/|blob:)/i.test(element.getAttribute('src') || '')) element.remove()
  })

  return parsed.body.innerHTML
}

const syncEditor = () => {
  if (editor.value && editor.value.innerHTML !== props.modelValue) editor.value.innerHTML = props.modelValue || ''
}

const emitContent = () => {
  const cleanValue = sanitizeContent(editor.value?.innerHTML || '')
  if (editor.value && editor.value.innerHTML !== cleanValue) editor.value.innerHTML = cleanValue
  emit('update:modelValue', cleanValue)
}

const runCommand = command => {
  editor.value?.focus()
  document.execCommand(command, false)
  emitContent()
}

const insertImage = url => {
  if (!url) return
  editor.value?.focus()
  document.execCommand('insertImage', false, url)
  emitContent()
}

const insertImageByUrl = () => {
  const url = window.prompt('Paste an image URL')
  if (/^https?:\/\//i.test(url || '')) insertImage(url.trim())
}

const chooseImageFile = () => imageInput.value?.click()

const handleImageFile = async event => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return

  uploadingImage.value = true
  try {
    const [url] = await uploadImages([file])
    insertImage(url)
  } finally {
    uploadingImage.value = false
  }
}

watch(() => props.modelValue, async () => {
  await nextTick()
  syncEditor()
}, { immediate: true })
</script>

<template>
  <div class="rich-text-editor">
    <label>{{ label }}</label>
    <div class="rich-text-toolbar" role="toolbar" :aria-label="`${label} formatting`">
      <button type="button" title="Bold" aria-label="Bold" @mousedown.prevent="runCommand('bold')"><strong>B</strong></button>
      <button type="button" title="Italic" aria-label="Italic" @mousedown.prevent="runCommand('italic')"><em>I</em></button>
      <button type="button" title="Underline" aria-label="Underline" @mousedown.prevent="runCommand('underline')"><u>U</u></button>
      <button type="button" title="Bulleted list" aria-label="Bulleted list" @mousedown.prevent="runCommand('insertUnorderedList')">&bull;</button>
      <button type="button" title="Numbered list" aria-label="Numbered list" @mousedown.prevent="runCommand('insertOrderedList')">1.</button>
      <button type="button" title="Insert image URL" aria-label="Insert image URL" @mousedown.prevent="insertImageByUrl">Image URL</button>
      <button type="button" title="Upload image" aria-label="Upload image" :disabled="uploadingImage" @mousedown.prevent="chooseImageFile">{{ uploadingImage ? 'Uploading...' : 'Upload image' }}</button>
      <input ref="imageInput" type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden @change="handleImageFile" />
    </div>
    <div
      ref="editor"
      class="rich-text-content"
      contenteditable="true"
      role="textbox"
      :aria-label="label"
      :data-placeholder="placeholder"
      :style="{ minHeight }"
      @input="emitContent"
    ></div>
  </div>
</template>
