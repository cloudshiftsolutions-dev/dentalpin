/**
 * Field validation for the leads forms.
 *
 * These are the **client-side guards**: they stop an obviously wrong value
 * from being sent and tell the user in their own language what is wrong.
 * The server stays the authority — pydantic validates the same payload and
 * answers 422, which the forms surface as a toast — but a round trip for a
 * typo'd email is bad manners and, on the convert drawer, would create
 * nothing while looking like it did.
 *
 * The per-field rules live in ``app/utils/contactValidation.ts`` (shared
 * with the patient forms) and mirror what the backend accepts, so a value
 * that passes here is not rejected there.
 *
 * Pure functions returning a message key, so the components stay thin and
 * the rules are unit-tested without mounting a form.
 */

import {
  isValidDateOfBirth,
  isValidEmail,
  isValidPhone,
  PATIENT_PHONE_MAX_LENGTH
} from '~~/app/utils/contactValidation'

export type ValidationKey = 'required' | 'email' | 'phone' | 'dateOfBirth'

function required(value: string | null | undefined): boolean {
  return Boolean(value && value.trim())
}

export interface LeadFormValues {
  full_name: string
  phone: string
  email: string
  motive: string
  description?: string
  availability?: string
}

export type LeadFormErrors = Partial<Record<keyof LeadFormValues, ValidationKey>>

/** Manual create / edit. Mirrors LeadCreate in schemas.py. */
export function validateLeadForm(values: LeadFormValues): LeadFormErrors {
  const errors: LeadFormErrors = {}
  if (!required(values.full_name)) errors.full_name = 'required'
  if (!isValidPhone(values.phone, { required: true, maxLength: 32 })) errors.phone = 'phone'
  if (required(values.email) && !isValidEmail(values.email)) errors.email = 'email'
  if (!required(values.motive)) errors.motive = 'required'
  return errors
}

export interface PatientFormValues {
  first_name: string
  last_name: string
  phone: string
  email: string
  date_of_birth: string
}

export type PatientFormErrors = Partial<Record<keyof PatientFormValues, ValidationKey>>

/** The convert drawer. Mirrors LeadConvertRequest + the patients columns
 *  (phone is String(20) there, which is where the 20 comes from). */
export function validatePatientForm(values: PatientFormValues): PatientFormErrors {
  const errors: PatientFormErrors = {}
  if (!required(values.first_name)) errors.first_name = 'required'
  if (!required(values.last_name)) errors.last_name = 'required'
  if (!isValidPhone(values.phone, { required: false, maxLength: PATIENT_PHONE_MAX_LENGTH })) errors.phone = 'phone'
  if (required(values.email) && !isValidEmail(values.email)) errors.email = 'email'
  if (!isValidDateOfBirth(values.date_of_birth)) errors.date_of_birth = 'dateOfBirth'
  return errors
}

export function hasErrors(errors: Record<string, ValidationKey | undefined>): boolean {
  return Object.values(errors).some(Boolean)
}
