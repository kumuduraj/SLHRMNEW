import { computed, reactive } from "vue"
import { createResource, call } from "frappe-ui"
import { userResource } from "./user"
import { employeeResource } from "./employee"
import { appPermissions } from "./appPermissions"
import router from "@/router"

export function sessionUser() {
	let cookies = new URLSearchParams(document.cookie.split("; ").join("&"))
	let _sessionUser = cookies.get("user_id")
	if (_sessionUser === "Guest") {
		_sessionUser = null
	}
	return _sessionUser
}

export function reloadSessionData() {
	userResource.reload()
	employeeResource.reload()
	appPermissions.reload()
}

function handleLogin(response) {
	if (response.message === "Logged In") {
		session.user = sessionUser()

		// Check first: while a password change is pending every other API answers 403
		call("slhrm.api.check_must_change_password").then((r) => {
			if (r.message) {
				session.mustChangePassword = true
				router.replace({ path: "/change-password" })
			} else {
				session.mustChangePassword = false
				reloadSessionData()
				router.replace({ path: "/" })
			}
		}).catch(() => {
			session.mustChangePassword = false
			reloadSessionData()
			router.replace({ path: "/" })
		})
	}
}

export const session = reactive({
	login: async (email, password) => {
		const response = await call("login", { usr: email, pwd: password })
		handleLogin(response)
		return response
	},
	otp: async (tmp_id, otp) => {
		const response = await call("login", { tmp_id, otp })
		handleLogin(response)
		return response
	},
	logout: createResource({
		url: "logout",
		onSuccess() {
			userResource.reset()
			employeeResource.reset()
			appPermissions.reset()

			session.user = sessionUser()
			session.mustChangePassword = false
			router.replace({ name: "Login" })
			window.location.reload()
		},
	}),
	user: sessionUser(),
	isLoggedIn: computed(() => !!session.user),
	mustChangePassword: false,
})
