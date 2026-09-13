export function applyFloorPreset(input: {
  floors: number;
  building_count: number;
  footprint_per_building: number;
  households: number;
  population: number;
  average_household_area: number;
}, floors: number) {
  const householdArea = Math.max(1, input.average_household_area);
  const households = Math.round((input.building_count * input.footprint_per_building * floors) / householdArea);
  const peoplePerHousehold = input.households > 0 ? input.population / input.households : 0;
  return { floors, households, population: Math.round(households * peoplePerHousehold) };
}
