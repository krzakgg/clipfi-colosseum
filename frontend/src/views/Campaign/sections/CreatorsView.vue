<script setup>
import ManageApplication from '../ManageApplication.vue'

defineProps({ campaign: { type: Object, required: true }, session: { type: Object, required: true }, isCompanyOwner: { type: Boolean, required: true } })
</script>

<template>
  <ManageApplication v-if="isCompanyOwner" :campaign-id="campaign.id" :company-id="session.user.id" section="creators" />
  <div v-else class="creator-access-message"><strong>Creators and applications</strong><span>Only the campaign owner can view creator applications.</span></div>
</template>
