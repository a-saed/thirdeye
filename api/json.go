package main

import "encoding/json"

// jsonUnmarshalLoose decodes a JSON string, tolerating a leading/trailing
// whitespace. Kept separate so load.go does not import encoding/json for one
// call and so the failure mode (return error, caller substitutes an empty
// map) is explicit.
func jsonUnmarshalLoose(s string, v any) error {
	return json.Unmarshal([]byte(s), v)
}
