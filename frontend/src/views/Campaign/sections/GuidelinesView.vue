<script setup>
defineProps({ guidelineItems: { type: Array, required: true }, talkingPoints: { type: Array, required: true } })
</script>

<template>
  <section class="guidelines-layout">
    <article class="guidelines-panel info-card"><div class="guidelines-heading"><div><span class="guidelines-eyebrow">Campaign brief</span><h2>Wytyczne marki</h2></div><span class="guidelines-count">{{ guidelineItems.length }} points</span></div>
      <ul v-if="guidelineItems.length" class="guidelines-list"><li v-for="(item, index) in guidelineItems" :key="`${item}-${index}`">{{ item }}</li></ul><p v-else class="guidelines-empty">No brand guidelines available.</p>
    </article>
    <article class="guidelines-panel info-card talking-points-panel"><div class="guidelines-heading"><div><span class="guidelines-eyebrow">Platform requirements</span><h2>Talking points</h2></div><span class="guidelines-count">{{ talkingPoints.length }}</span></div>
      <ul v-if="talkingPoints.length" class="guidelines-list compact-list"><li v-for="(point, index) in talkingPoints" :key="`${point}-${index}`">{{ point }}</li></ul><p v-else class="guidelines-empty">No additional platform requirements.</p>
    </article>
  </section>
</template>
