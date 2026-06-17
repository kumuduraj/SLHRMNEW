<template>
	<BaseLayout pageTitle="Team Check-in">
		<template #body>
			<div class="flex flex-col my-7 p-4 gap-5">
			<div class="flex items-center gap-2">
				<Button
					@click="goToPrevDay"
					variant="subtle"
					class="py-2 px-3"
				>
					<FeatherIcon name="chevron-left" class="w-4" />
				</Button>
				<div class="flex-1 text-center">
					<div class="font-semibold text-gray-800">
						{{ dayjs(selectedDate).format("ddd, D MMM YYYY") }}
					</div>
					<div v-if="isToday" class="text-xs text-gray-500 font-normal">
						{{ __("Today") }}
					</div>
				</div>
				<input
					ref="dateInput"
					type="date"
					:value="selectedDate"
					@change="onDatePick"
					class="sr-only"
				/>
				<Button @click="$refs.dateInput.showPicker()" variant="subtle" class="py-2 px-3">
					<FeatherIcon name="calendar" class="w-4" />
				</Button>
				<Button @click="goToNextDay" variant="subtle" class="py-2 px-3">
					<FeatherIcon name="chevron-right" class="w-4" />
				</Button>
				<Button @click="goToToday" v-if="!isToday" variant="subtle" class="py-2 px-3 text-sm">
					{{ __("Today") }}
				</Button>
			</div>

				<div v-if="teamCheckins.loading" class="text-center text-gray-500 py-10">
					{{ __("Loading...") }}
				</div>

				<div v-else-if="teamCheckins.data" class="flex flex-col gap-3">
					<div v-if="teamCheckins.data.length === 0" class="text-center text-gray-500 py-10">
						{{ __("No team members found") }}
					</div>
					<div
						v-for="member in teamCheckins.data"
						:key="member.employee"
						class="flex items-center gap-3 p-3 bg-white rounded-lg border"
					>
						<EmployeeAvatar :employeeID="member.employee" :size="'lg'" />
						<div class="flex-1 min-w-0">
							<div class="font-semibold text-gray-800 truncate">
								{{ member.employee_name }}
							</div>
							<div class="text-sm text-gray-500">
								{{ member.designation || "" }}
							</div>
						</div>
						<div class="flex flex-col items-end gap-1">
							<span
								class="px-2 py-0.5 rounded-full text-xs font-medium"
								:class="getStatusClass(member)"
							>
								{{ getStatusLabel(member) }}
							</span>
							<div v-if="member.last_checkin" class="text-xs text-gray-400">
								{{ formatTime(member.last_checkin) }}
							</div>
						</div>
					</div>
				</div>

				<div
					v-if="teamCheckins.data && teamCheckins.data.length > 0"
					class="flex justify-around p-3 bg-gray-50 rounded-lg"
				>
					<div class="text-center">
						<div class="text-lg font-bold text-green-600">{{ presentCount }}</div>
						<div class="text-xs text-gray-500">{{ __("Present") }}</div>
					</div>
					<div class="text-center">
						<div class="text-lg font-bold text-red-500">{{ absentCount }}</div>
						<div class="text-xs text-gray-500">{{ __("Absent") }}</div>
					</div>
					<div class="text-center">
						<div class="text-lg font-bold text-gray-400">{{ totalCount }}</div>
						<div class="text-xs text-gray-500">{{ __("Total") }}</div>
					</div>
				</div>
			</div>
		</template>
	</BaseLayout>
</template>

<script setup>
import { inject, computed, ref, watch } from "vue"
import { createResource, FeatherIcon } from "frappe-ui"

import BaseLayout from "@/components/BaseLayout.vue"
import EmployeeAvatar from "@/components/EmployeeAvatar.vue"

const dayjs = inject("$dayjs")
const __ = inject("$translate")
const employee = inject("$employee")

const selectedDate = ref(dayjs().format("YYYY-MM-DD"))
const dateInput = ref(null)

const isToday = computed(() => {
	return dayjs(selectedDate.value).isSame(dayjs(), "day")
})

function goToPrevDay() {
	selectedDate.value = dayjs(selectedDate.value).subtract(1, "day").format("YYYY-MM-DD")
}

function goToNextDay() {
	selectedDate.value = dayjs(selectedDate.value).add(1, "day").format("YYYY-MM-DD")
}

function goToToday() {
	selectedDate.value = dayjs().format("YYYY-MM-DD")
}

function onDatePick(e) {
	selectedDate.value = e.target.value
}

const teamCheckins = createResource({
	url: "slhrm.api.get_team_checkins",
	params: {
		employee: employee.data?.name,
		date: selectedDate.value,
	},
	auto: true,
})

watch(selectedDate, (newDate) => {
	teamCheckins.params.date = newDate
	teamCheckins.params.employee = employee.data?.name
	teamCheckins.reload()
})

const presentCount = computed(() => {
	if (!teamCheckins.data) return 0
	return teamCheckins.data.filter((m) => m.log_type === "IN").length
})

const absentCount = computed(() => {
	if (!teamCheckins.data) return 0
	return teamCheckins.data.filter((m) => !m.log_type).length
})

const totalCount = computed(() => {
	return teamCheckins.data?.length || 0
})

function getStatusClass(member) {
	if (member.log_type === "IN") return "bg-green-100 text-green-700"
	if (member.log_type === "OUT") return "bg-yellow-100 text-yellow-700"
	return "bg-red-100 text-red-600"
}

function getStatusLabel(member) {
	if (member.log_type === "IN") return __("Checked In")
	if (member.log_type === "OUT") return __("Checked Out")
	return __("No Record")
}

function formatTime(time) {
	if (!time) return ""
	return dayjs(time).format("hh:mm A")
}
</script>
