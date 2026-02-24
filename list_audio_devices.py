import sounddevice as sd

def list_devices():
    print("=" * 60)
    print(f"{'Index':<7} {'Name':<40} {'In/Out'}")
    print("-" * 60)
    
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        in_ch = dev['max_input_channels']
        out_ch = dev['max_output_channels']
        
        # Mark the default input/output
        default_mark = ""
        if i == sd.default.device[0]:
            default_mark += " [Default Input]"
        if i == sd.default.device[1]:
            default_mark += " [Default Output]"
            
        print(f"{i:<7} {dev['name'][:40]:<40} {in_ch}/{out_ch}{default_mark}")
    print("=" * 60)

if __name__ == "__main__":
    list_devices()
