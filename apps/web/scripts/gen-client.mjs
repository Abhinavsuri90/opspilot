import { readFileSync, writeFileSync } from "node:fs";
import openapiTS, { astToString } from "openapi-typescript";
import ts from "typescript";

const schema = JSON.parse(readFileSync("lib/openapi.json", "utf8"));
const ast = await openapiTS(schema, {
  transform(schemaObject) {
    if (schemaObject.format === "binary" || schemaObject.contentMediaType === "application/octet-stream") {
      return ts.factory.createTypeReferenceNode(ts.factory.createIdentifier("Blob"));
    }
  },
});
writeFileSync("lib/schema.d.ts", astToString(ast));
