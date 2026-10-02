<script setup>
import ApplyToCampaign from '../ApplyToCampaign.vue'
import ManageApplication from '../ManageApplication.vue'
import SubmitCampaignVideo from '../SubmitCampaignVideo.vue'

defineProps({
  campaign: { type: Object, required: true }, session: { type: Object, required: true },
  canApplyToCampaign: { type: Boolean, required: true }, canSubmitCampaignVideo: { type: Boolean, required: true },
  creatorApplicationLoading: { type: Boolean, required: true }, creatorApplicationStatus: { type: String, default: null },
  isCompanyOwner: { type: Boolean, required: true }
})
</script>

<template>
  <div>
    <ApplyToCampaign v-if="canApplyToCampaign" :campaign-id="campaign.id" :creator-id="session.user.id" />
    <SubmitCampaignVideo v-if="canSubmitCampaignVideo" :campaign-id="campaign.id" :creator-id="session.user.id" />
    <div v-else-if="session.account_type === 'creator'" class="creator-access-message">
      <strong v-if="creatorApplicationLoading">Checking campaign access...</strong>
      <template v-else-if="creatorApplicationStatus === 'pending'"><strong>Application pending</strong><span>Video submissions become available after the company accepts your application.</span></template>
      <template v-else-if="creatorApplicationStatus === 'rejected'"><strong>Application not accepted</strong><span>You cannot submit materials to this campaign.</span></template>
      <template v-else><strong>Join the campaign first</strong><span>Apply and wait for company approval before submitting a video.</span></template>
    </div>
    <ManageApplication v-else-if="isCompanyOwner" :campaign-id="campaign.id" :company-id="session.user.id" section="submissions" />
  </div>
</template>
