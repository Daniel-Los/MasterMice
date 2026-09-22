package config

// NextDPI includes the maximum even when the increment does not divide the range.
func (s Settings) NextDPI(current, limit int) int {
	start := s.DPICycleStart
	if start < 200 {
		start = 200
	}
	if start > limit {
		start = limit
	}
	maximum := s.DPICycleMax
	if maximum > limit {
		maximum = limit
	}
	if maximum < start {
		maximum = start
	}
	step := s.DPICycleStep
	if step < 50 {
		step = 50
	}
	if current < start || current >= maximum {
		return start
	}
	if step >= maximum-current {
		return maximum
	}
	return current + step
}
