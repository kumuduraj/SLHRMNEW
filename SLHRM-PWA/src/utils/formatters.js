import dayjs from "@/utils/dayjs"
import { bootFormats } from "@/data/formats"

export const formatCurrency = (value, currency) => {
	if (!currency) return value

	// hack: if value contains a space, it is already formatted
	if (value?.toString().trim().includes(" ")) return value

	const { country, language } = bootFormats()
	const locale = country == "India" ? "en-IN" : language

	const formatter = Intl.NumberFormat(locale, {
		style: "currency",
		currency: currency,
		trailingZeroDisplay: "stripIfInteger",
		currencyDisplay: "narrowSymbol",
	})
	return (
		formatter
			.format(value)
			// add space between the digits and symbol
			.replace(/^(\D+)/, "$1 ")
			// remove extra spaces if any (added by some browsers)
			.replace(/\s+/, " ")
	)
}

export const formatTimestamp = (timestamp) => {
	const formattedTime = dayjs(timestamp).format("hh:mm a")

	if (dayjs(timestamp).isToday()) return formattedTime
	else if (dayjs(timestamp).isYesterday()) return `${formattedTime} yesterday`
	else if (dayjs(timestamp).isSame(dayjs(), "year"))
		return `${formattedTime} on ${dayjs(timestamp).format("D MMM")}`

	return `${formattedTime} on ${dayjs(timestamp).format("D MMM, YYYY")}`
}
