# Burp Suite Extension: Archives URL Fetcher
# Author: K Lovett
# Description: This extension adds a new tab to Burp Suite that allows fetching
#              historical URLs for a given domain from archive.org,
#              filters them, and checks their HTTP status with multiple threads.

from burp import IBurpExtender, ITab
from javax.swing import (JPanel, JLabel, JTextField, JButton, JScrollPane,
                         JTextArea, BoxLayout, Box, SwingUtilities, JComboBox,
                         JFileChooser)
from javax.swing.border import EmptyBorder
from java.awt import BorderLayout, Dimension, FlowLayout
import threading
from java.net import URL
from java.io import BufferedReader, InputStreamReader, FileWriter
import sys
from Queue import Queue
from java.lang import Runnable

# Python 2/3 compatibility
if sys.version_info[0] == 3:
    from urllib.parse import quote
else:
    from urllib import quote

# A helper class to safely update Swing components from background threads
class UpdateUI(Runnable):
    def __init__(self, component, new_text):
        self.component = component
        self.new_text = new_text
    def run(self):
        self.component.setText(self.new_text)

class BurpExtender(IBurpExtender, ITab):
    """
    Main class for the Burp Suite extension.
    """

    def registerExtenderCallbacks(self, callbacks):
        """
        This method is invoked when the extension is loaded. It registers the
        extension with Burp Suite.
        """
        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        callbacks.setExtensionName("Archives URL Fetcher")

        # Create a thread-safe event to signal stopping
        self._stop_event = threading.Event()
        # Create a lock for thread-safe counter updates
        self._counter_lock = threading.Lock()
        self._checked_count = 0

        # Create the UI components
        self._build_ui()

        # Add the custom tab to Burp's UI
        callbacks.addSuiteTab(self)
        
        print("Archives URL Fetcher extension loaded successfully.")

    # Implementation of ITab
    def getTabCaption(self):
        """
        Returns the name of the tab that will be displayed in Burp's UI.
        """
        return "Archives"

    def getUiComponent(self):
        """
        Returns the main UI component for the custom tab.
        """
        return self.mainPanel

    # UI Building and Event Handling
    def _build_ui(self):
        """
        Constructs the user interface for the extension's tab.
        """
        self.mainPanel = JPanel(BorderLayout(10, 10))
        self.mainPanel.setBorder(EmptyBorder(10, 10, 10, 10)) # Add padding on all sides

        # --- Input Panel ---
        controlsPanel = JPanel()
        controlsPanel.setLayout(BoxLayout(controlsPanel, BoxLayout.X_AXIS))

        domainLabel = JLabel("Domain:")
        self.domainField = JTextField("", 20)
        self.domainField.setMaximumSize(Dimension(200, 30))

        limitLabel = JLabel("Limit:")
        self.limitField = JTextField("10000", 8)
        self.limitField.setMaximumSize(Dimension(80, 30))

        threadsLabel = JLabel("Threads:")
        threadOptions = [str(i) for i in range(1, 11)]
        self.threadsDropdown = JComboBox(threadOptions)
        self.threadsDropdown.setSelectedItem("5")
        self.threadsDropdown.setMaximumSize(Dimension(60, 30))

        self.fetchButton = JButton("Fetch & Check URLs", actionPerformed=self._on_fetch_button_click)
        self.stopButton = JButton("Stop", actionPerformed=self._on_stop_button_click)
        self.stopButton.setEnabled(False)
        self.downloadButton = JButton("Download Log", actionPerformed=self._on_download_button_click)
        self.clearButton = JButton("Clear Log", actionPerformed=self._on_clear_button_click)
        
        controlsPanel.add(domainLabel)
        controlsPanel.add(Box.createRigidArea(Dimension(5, 0)))
        controlsPanel.add(self.domainField)
        controlsPanel.add(Box.createRigidArea(Dimension(10, 0)))
        controlsPanel.add(limitLabel)
        controlsPanel.add(Box.createRigidArea(Dimension(5, 0)))
        controlsPanel.add(self.limitField)
        controlsPanel.add(Box.createRigidArea(Dimension(10, 0)))
        controlsPanel.add(threadsLabel)
        controlsPanel.add(Box.createRigidArea(Dimension(5, 0)))
        controlsPanel.add(self.threadsDropdown)
        controlsPanel.add(Box.createRigidArea(Dimension(15, 0)))
        controlsPanel.add(self.fetchButton)
        controlsPanel.add(Box.createRigidArea(Dimension(5, 0)))
        controlsPanel.add(self.stopButton)
        controlsPanel.add(Box.createHorizontalGlue())

        # --- Output Panel ---
        self.outputArea = JTextArea()
        self.outputArea.setEditable(False)
        self.outputArea.setLineWrap(True)
        self.outputArea.setWrapStyleWord(True)
        scrollPane = JScrollPane(self.outputArea)

        # --- Bottom Panel (Status + Actions) ---
        statusPanel = JPanel(FlowLayout(FlowLayout.LEFT, 10, 5))
        self.statusLabel = JLabel("Status: Idle")
        statusPanel.add(self.statusLabel)

        actionsPanel = JPanel(FlowLayout(FlowLayout.RIGHT, 5, 0))
        actionsPanel.add(self.downloadButton)
        actionsPanel.add(self.clearButton)

        bottomPanel = JPanel(BorderLayout())
        bottomPanel.add(statusPanel, BorderLayout.WEST)
        bottomPanel.add(actionsPanel, BorderLayout.EAST)

        self.mainPanel.add(controlsPanel, BorderLayout.NORTH)
        self.mainPanel.add(scrollPane, BorderLayout.CENTER)
        self.mainPanel.add(bottomPanel, BorderLayout.SOUTH)


    def _on_fetch_button_click(self, event):
        """
        Handles the click event for the 'Fetch URLs' button.
        """
        self._stop_event.clear()
        thread = threading.Thread(target=self._fetch_and_check_urls)
        thread.start()

    def _on_stop_button_click(self, event):
        """Handles the click event for the 'Stop' button."""
        self.outputArea.append("\n[*] Stop request received. Finishing current checks...\n")
        self._stop_event.set()
        self.stopButton.setEnabled(False)

    def _on_download_button_click(self, event):
        """Handles the click event for the 'Download Log' button."""
        chooser = JFileChooser()
        chooser.setDialogTitle("Save Output Log")
        return_val = chooser.showSaveDialog(self.mainPanel)

        if return_val == JFileChooser.APPROVE_OPTION:
            file_to_save = chooser.getSelectedFile()
            writer = None
            try:
                writer = FileWriter(file_to_save)
                writer.write(self.outputArea.getText())
            except Exception as e:
                self._callbacks.issueAlert("Error saving file: {}".format(e))
            finally:
                if writer:
                    writer.close()

    def _on_clear_button_click(self, event):
        """Handles the click event for the 'Clear Log' button."""
        self.outputArea.setText("")
        SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Idle"))

    def _url_checker(self, q, results, total_urls):
        """Worker thread function to process URLs from the queue."""
        while not q.empty() and not self._stop_event.is_set():
            url_string = q.get()
            try:
                if not url_string.startswith(('http://', 'https://')):
                    url_string = "http://" + url_string
                
                check_url = URL(url_string)
                conn = check_url.openConnection()
                conn.setInstanceFollowRedirects(False)
                conn.setConnectTimeout(5000)
                conn.setReadTimeout(10000)
                conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36")

                status = conn.getResponseCode()

                if status not in [400, 404]:
                    size = conn.getContentLength()
                    results.append((status, size, url_string))

            except Exception as e_check:
                results.append((-1, -1, "[!] Error on {}: {}".format(url_string, str(e_check))))
            
            finally:
                with self._counter_lock:
                    self._checked_count += 1
                    status_text = "Checking: {} / {}".format(self._checked_count, total_urls)
                    SwingUtilities.invokeLater(UpdateUI(self.statusLabel, status_text))
                q.task_done()

    def _fetch_and_check_urls(self):
        """
        Fetches, filters, and checks URLs from the Wayback Machine.
        """
        self.fetchButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self._checked_count = 0
        SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Starting..."))

        try:
            domain = self.domainField.getText().strip()
            if not domain:
                self.outputArea.setText("Error: Please enter a domain name.")
                SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Error"))
                return

            try:
                limit = int(self.limitField.getText().strip())
            except ValueError:
                self.outputArea.setText("Error: Invalid limit. Please enter a number.")
                SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Error"))
                return
            
            thread_count = int(self.threadsDropdown.getSelectedItem())

            self.outputArea.setText("[*] Preparing to fetch URLs for: {}\n".format(domain))
            
            encoded_domain = quote(domain)
            target_url = (
                "http://web.archive.org/cdx/search/cdx?url={}&matchType=domain"
                "&limit={}&fl=original&collapse=urlkey".format(encoded_domain, limit)
            )
            
            self.outputArea.append("[*] Contacting: {}\n".format(target_url))

            url_connection = URL(target_url).openConnection()
            url_connection.setConnectTimeout(15000)
            url_connection.setReadTimeout(30000)
            
            reader = BufferedReader(InputStreamReader(url_connection.getInputStream()))
            
            lines = []
            line = reader.readLine()
            while line is not None:
                lines.append(line)
                line = reader.readLine()
            reader.close()
            
            if not lines:
                self.outputArea.append("\n[!] Error retrieving archived URLs. The response was empty.")
                SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Error"))
                return

            self.outputArea.append("[*] Found {} total URLs.\n".format(len(lines)))

            excluded_extensions = ['.eot', '.svg', '.woff', '.woff2', '.css', '.ttf', '.png', '.jpg', '.jpeg', '.gif']
            filtered_urls = [
                url for url in lines if not any(url.lower().endswith(ext) for ext in excluded_extensions)
            ]
            total_to_check = len(filtered_urls)
            
            self.outputArea.append(
                "[*] {} URLs remain after filtering. Starting HTTP checks with {} threads...\n\n".format(total_to_check, thread_count)
            )
            SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Checking: 0 / {}".format(total_to_check)))

            q = Queue()
            for url in filtered_urls:
                q.put(url)
            
            results = []
            threads = []
            for _ in range(thread_count):
                t = threading.Thread(target=self._url_checker, args=[q, results, total_to_check])
                t.daemon = True
                threads.append(t)
                t.start()
            
            q.join()

            sorted_results = sorted(results, key=lambda item: item[1], reverse=True)

            headers = "{:<8} {:<15} {}\n".format("Status", "Response Size", "URL")
            separator = "{:<8} {:<15} {}\n".format("------", "-------------", "---")
            self.outputArea.append(headers)
            self.outputArea.append(separator)
            
            for result_item in sorted_results:
                status, size, url_string = result_item
                
                if status == -1:
                    self.outputArea.append(url_string + "\n")
                else:
                    size_str = str(size) if size != -1 else "N/A"
                    result_line = "{:<8} {:<15} {}\n".format(status, size_str, url_string)
                    self.outputArea.append(result_line)

            if self._stop_event.is_set():
                 self.outputArea.append("\n[*] Process stopped by user.")
                 SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Stopped"))
            else:
                 self.outputArea.append("\n[*] All checks complete.")
                 SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Complete"))

            self.outputArea.setCaretPosition(0)

        except Exception as e_fetch:
            error_message = "[!] Error retrieving archived URLs.\n"
            error_message += "    Please check the domain and your network connection.\n\n"
            error_message += "    Error details: {}\n".format(str(e_fetch))
            self.outputArea.setText(error_message)
            SwingUtilities.invokeLater(UpdateUI(self.statusLabel, "Status: Fetch Error"))

        finally:
            self.fetchButton.setEnabled(True)
            self.stopButton.setEnabled(False)

