import pyvisa
import datetime
import os
import time

from pyvisa.resources import MessageBasedResource

def open_scope(resource_name: str) -> MessageBasedResource:
    """
    Otwiera połączenie z oscyloskopem i ustawia podstawowe parametry komunikacji.
    Zwraca obiekt typu MessageBasedResource, co pomaga uniknąć warningów w PyCharm.
    """
    rm = pyvisa.ResourceManager()
    scope: MessageBasedResource = rm.open_resource(resource_name)

    # Zwiększamy timeout i chunk_size, bo przy zrzutach ekranu może być dużo danych
    scope.timeout = 20000
    scope.chunk_size = 102400

    scope.write_termination = '\n'
    scope.read_termination = '\n'

    # Wyłączamy dodatkowe nagłówki SCPI, jeśli oscyloskop je wysyła
    scope.write(':SYSTem:HEADer OFF')

    return scope

def autoscale_oscilloscope(resource_name: str, wait_time: float = 1.0) -> None:
    """
    Otwiera połączenie z oscyloskopem i wykonuje komendę :AUToscale.
    Następnie (opcjonalnie) czeka 'wait_time' sekund, aby oscylogram zdążył się wyświetlić.
    """
    scope = open_scope(resource_name)
    try:
        scope.write(':AUToscale')
        # Możesz dostosować czas oczekiwania w zależności od potrzeb Twojego oscyloskopu
        time.sleep(wait_time)
    finally:
        scope.close()

def read_binblock(scope: MessageBasedResource) -> bytes:
    """
    Czyta binblock w formacie '#NLLLL...(dane)' w pętli,
    aż pobierzemy całą wskazaną liczbę bajtów (LLLL).
    Zwraca surowe bajty (bytes).
    """
    header = scope.read_bytes(2)
    if not header.startswith(b'#'):
        raise ValueError(f"Niepoprawny nagłówek binblock (brak '#'): {header}")

    digits = int(header[1:2])
    length_str = scope.read_bytes(digits)
    data_length = int(length_str)

    data = bytearray()
    bytes_left = data_length
    chunk = 65536

    while bytes_left > 0:
        to_read = min(chunk, bytes_left)
        block = scope.read_bytes(to_read)
        data.extend(block)
        bytes_left -= len(block)

    return bytes(data)

def capture_screenshot_display(resource_name: str,
                               folder: str = r"C:\Users\35387\Pictures\Screenshots"
                               ) -> None:
    """
    Otwiera połączenie z oscyloskopem, pobiera zrzut ekranu
    poleceniem :DISPlay:DATA? PNG, COLOR w formie binblock i zapisuje plik PNG
    z unikalną nazwą zawierającą timestamp.
    """
    scope = open_scope(resource_name)

    try:
        # Komenda do pobrania screenshotu w formacie PNG, w kolorze
        scope.write(':DISPlay:DATA? PNG, COLOR')

        # Wczytujemy binblock
        image_data = read_binblock(scope)

        # Budujemy unikalną nazwę pliku z datą i godziną
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"scope_screenshot_{timestamp_str}.png"

        # Upewniamy się, że folder docelowy istnieje
        os.makedirs(folder, exist_ok=True)

        full_path = os.path.join(folder, filename)
        with open(full_path, 'wb') as f:
            f.write(image_data)

        print(f"Screenshot zapisany do: {full_path}")

    finally:
        scope.close()


if __name__ == '__main__':
    resource_name = "USB0::0x0957::0x17A4::MY58250706::INSTR"

    # 1. Najpierw auto-scale i czas zwloki
    autoscale_oscilloscope(resource_name, wait_time=3.0)

    # 2. Następnie screenshot
    capture_screenshot_display(resource_name)
