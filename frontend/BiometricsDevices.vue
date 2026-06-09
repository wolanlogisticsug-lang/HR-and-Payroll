<template>
  <div class="p-6 bg-white rounded-lg shadow-md">
    <h2 class="text-xl font-bold mb-4">Biometric Terminals Registry</h2>
    
    <form @submit.prevent="registerDevice" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
      <input v-model="form.name" placeholder="Device Name (e.g., Warehouse Door)" class="border p-2 rounded w-full" required />
      <select v-model="form.device_type" class="border p-2 rounded w-full" required>
        <option value="zkteco">ZKTeco Terminal</option>
        <option value="hikvision">Hikvision Terminal</option>
      </select>
      <input v-model="form.ip_address" placeholder="IP Address (e.g., 192.168.1.15)" class="border p-2 rounded w-full" required />
      <button type="submit" class="bg-blue-600 text-white p-2 rounded hover:bg-blue-700 transition">Add Device</button>
    </form>

    <table class="w-full text-left border-collapse">
      <thead>
        <tr class="bg-gray-100 border-b">
          <th class="p-3">Name</th>
          <th class="p-3">Type</th>
          <th class="p-3">IP Address</th>
          <th class="p-3">Last Polled</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="device in devices" :key="device.id" class="border-b hover:bg-gray-50">
          <td class="p-3 font-semibold">{{ device.name }}</td>
          <td class="p-3 uppercase text-xs text-gray-600">{{ device.device_type }}</td>
          <td class="p-3 font-mono text-sm bg-gray-50 rounded px-1">{{ device.ip_address }}</td>
          <td class="p-3 text-sm text-gray-500">{{ device.last_sync_at || 'Never Polled' }}</td>
        </tr>
        <tr v-if="devices.length === 0">
          <td colspan="4" class="p-4 text-center text-gray-500">No biometric terminals configured yet.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const devices = ref([])
const form = ref({ name: '', device_type: 'zkteco', ip_address: '', port: 4370 })

// NOTE: Since we placed the endpoints inside the onboarding app URLs, 
// the default relative path prefixes with /onboarding/
const fetchDevices = async () => {
  try {
    const res = await fetch('/onboarding/api/v1/biometric/devices')
    if (res.ok) {
      devices.value = await res.json()
    }
  } catch (err) {
    console.error("Error pulling registry data:", err)
  }
}

const registerDevice = async () => {
  try {
    const res = await fetch('/onboarding/api/v1/biometric/devices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value)
    })
    if (res.ok) {
      form.value = { name: '', device_type: 'zkteco', ip_address: '', port: 4370 }
      fetchDevices() // Refresh list
    }
  } catch (err) {
    console.error("Registration engine error:", err)
  }
}

onMounted(fetchDevices)
</script>