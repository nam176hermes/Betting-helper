import { ContractNotImplementedError } from "./errors.js";

import { Ajv2020, type AnySchemaObject, type ErrorObject } from "ajv/dist/2020.js";
import addFormatsImport, { type FormatsPlugin } from "ajv-formats";

const addFormats = addFormatsImport as unknown as FormatsPlugin;

export const validateArtifact = (
  artifact: unknown,
  schemaId?: string,
  schemas?: readonly AnySchemaObject[],
): void => {
  if (schemaId === undefined || schemas === undefined) {
    throw new ContractNotImplementedError("F0A-T02");
  }
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  for (const schema of schemas) ajv.addSchema(schema);
  const validate = ajv.getSchema(schemaId);
  if (validate === undefined) throw new Error(`E_SCHEMA:UNKNOWN:${schemaId}`);
  if (!validate(artifact)) {
    const errors: ErrorObject[] = validate.errors ?? [];
    throw new Error(`E_SCHEMA:INVALID:${JSON.stringify(errors)}`);
  }
};
