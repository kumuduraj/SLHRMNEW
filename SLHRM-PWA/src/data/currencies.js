import { createResource } from "frappe-ui"
import { bootFormats } from "./formats"

const companyCurrency = createResource({
	url: "hrms.api.get_company_currencies",
	auto: true,
})

const currencySymbols = createResource({
	url: "hrms.api.get_currency_symbols",
	auto: true,
})

export function getCompanyCurrency(company) {
	return companyCurrency?.data?.[company]?.[0]
}

export function getCompanyCurrencySymbol(company) {
	return companyCurrency?.data?.[company]?.[1]
}

export function getCurrencySymbol(currency) {
	return currencySymbols?.data?.[currency]
}

// from the boot page: System Settings is not readable for the Employee role
export const currencyPrecision = {
	get data() {
		return bootFormats().currency_precision
	},
}
