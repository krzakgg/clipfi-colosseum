<script setup>
defineProps({ campaign: { type: Object, required: true }, formatDate: { type: Function, required: true } })
</script>

<template>
  <section class="about-layout">
    <main class="about-main"><article class="info-card about-card">
      <h2>Campaign details</h2><p>Key collaboration and campaign delivery requirements.</p>
      <div class="creator-requirements detail-requirements"><span>Min. views <strong>{{ campaign.min_views || 0 }}</strong></span><span>Min. followers <strong>{{ campaign.min_subscribers || 0 }}</strong></span><span>Videos per creator <strong>{{ campaign.max_videos_per_creator || 'Unlimited' }}</strong></span></div>
    </article></main>
    <aside class="about-sidebar"><article class="info-card summary-card"><h2>Campaign information</h2><dl>
      <div><dt>Total budget</dt><dd>{{ campaign.total_budget }} PLN</dd></div><div><dt>Budget per creator</dt><dd>{{ campaign.budget_per_creator || 'To be decided' }}{{ campaign.budget_per_creator ? ' PLN' : '' }}</dd></div><div><dt>Languages</dt><dd>{{ campaign.languages?.join(', ') || 'Not specified' }}</dd></div><div><dt>Tags</dt><dd>{{ campaign.tags?.join(', ') || 'No tags' }}</dd></div><div><dt>Dates</dt><dd>{{ formatDate(campaign.start_date) }} - {{ formatDate(campaign.end_date) }}</dd></div>
    </dl></article></aside>
  </section>
</template>
