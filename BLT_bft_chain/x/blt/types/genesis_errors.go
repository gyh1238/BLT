package types

import "fmt"

func errInitialDelegatesLen(got, want uint32) error {
	return fmt.Errorf("initial_delegates length %d does not match cluster_count %d", got, want)
}

func errDuplicateClusterID(id uint32) error {
	return fmt.Errorf("duplicate cluster_id %d in initial_delegates", id)
}
