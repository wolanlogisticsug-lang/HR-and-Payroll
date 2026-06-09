<template>
  <div class="p-6 bg-white rounded-lg shadow-md max-w-xl mx-auto text-center">
    <h2 class="text-2xl font-bold mb-2">Hardware Polling Hub</h2>
    <p class="text-gray-600 mb-6 text-sm">Force an immediate synchronization loop across all active remote biometric terminals.</p>
    
    <button 
      @click="triggerGlobalSync" 
      :disabled="processing" 
      class="w-full bg-emerald-600 text-white font-bold py-3 px-4 rounded hover:bg-emerald-700 transition disabled:opacity-50">
      {{ processing ? 'Polling Active Hardware Terminals...' : 'Fire Global Terminal Ingestion Sequence' }}
    </button>

    <div v-if="syncReport" class="mt-6 text-left bg-gray-50 p-4 rounded border text-sm font-mono">
      <h3 class="font-bold border-b pb-2 mb-2 text-gray-800">Engine Ingestion Response:</h3>
      <pre class="whitespace-pre-wrap text-xs text-gray-700">{{ JSON.stringify(syncReport, null, 2) }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const processing = ref(false)
const syncReport = ref(null)

const triggerGlobalSync = async () => {
  processing.value = true
  syncReport.value = null
  try {
    // Calling the endpoint mapped in onboarding/urls.py
    const res = await fetch('/onboarding/api/v1/biometric/sync', { method: 'POST' })
    syncReport.value = await res.json()
  } catch (err) {
    syncReport.value = { error: "Network fault tracking synchronization pipeline." }
  } finally {
    processing.value = false
  }
}
</script>