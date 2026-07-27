import time

class Guardian:
    def __init__(self, vr_temp_target, asic_temp_target):
        self.vr_temp_target = vr_temp_target
        self.asic_temp_target = asic_temp_target

    def monitor_temperatures(self, get_vr_temp, get_asic_temp, set_cooling_level):
        while True:
            vr_temp = get_vr_temp()
            asic_temp = get_asic_temp()

            if vr_temp > self.vr_temp_target:
                set_cooling_level('vr', 'increase')
            elif vr_temp < self.vr_temp_target - 5:  # Allow some hysteresis
                set_cooling_level('vr', 'decrease')

            if asic_temp > self.asic_temp_target:
                set_cooling_level('asic', 'increase')
            elif asic_temp < self.asic_temp_target - 5:  # Allow some hysteresis
                set_cooling_level('asic', 'decrease')

            time.sleep(10)  # Check temperatures every 10 seconds

# Example usage
def get_vr_temp():
    return 75  # Simulated VR temperature

def get_asic_temp():
    return 80  # Simulated ASIC temperature

def set_cooling_level(component, action):
    print(f"Setting {component} cooling to {action}")

guardian = Guardian(vr_temp_target=70, asic_temp_target=85)
guardian.monitor_temperatures(get_vr_temp, get_asic_temp, set_cooling_level)
