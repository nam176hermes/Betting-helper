import { ContractNotImplementedError } from "./errors.js";
import { Ajv2020 } from "ajv/dist/2020.js";
import addFormatsImport, {} from "ajv-formats";
const addFormats = addFormatsImport;
export const validateArtifact = (artifact, schemaId, schemas) => {
    if (schemaId === undefined || schemas === undefined) {
        throw new ContractNotImplementedError("F0A-T02");
    }
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);
    for (const schema of schemas)
        ajv.addSchema(schema);
    const validate = ajv.getSchema(schemaId);
    if (validate === undefined)
        throw new Error(`E_SCHEMA:UNKNOWN:${schemaId}`);
    if (!validate(artifact)) {
        const errors = validate.errors ?? [];
        throw new Error(`E_SCHEMA:INVALID:${JSON.stringify(errors)}`);
    }
};
