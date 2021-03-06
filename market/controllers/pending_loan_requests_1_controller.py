from PyQt5 import QtWidgets


class PendingLoanRequests1Controller:
    """
    Create a PendingLoanRequests1Controller object that performs tasks on the Pending Loan Request 1 section of the gui.
    Takes a MainWindowController object during construction.
    """
    def __init__(self, mainwindow):
        self.mainwindow = mainwindow
        self.loan_request_table = self.mainwindow.fiplr1_loan_requests_table
        self.loan_requests = []

        # Add listener to the 'view loan request' button and the table
        self.mainwindow.fiplr1_view_loan_request_pushbutton.clicked.connect(self.show_request)
        self.loan_request_table.doubleClicked.connect(self.show_request)

    def setup_view(self):
        """
        Setup the view with up-to-date data. Clears and reloads the table on re-entry of the page.
        """
        # Clear table
        self.loan_request_table.setRowCount(0)

        # Getting the loan requests for the bank
        self.loan_requests = self.mainwindow.api.load_all_loan_requests(self.mainwindow.app.user)

        # If the list is empty, do nothing. Otherwise fill table
        if self.loan_requests:
            # Fill the mortgage table
            for [loan_request, house] in self.loan_requests:
                # Property Address, Campaign Status, Investment Status, Amount Invested, Interest, Duration
                address = house.address + ' ' + house.house_number + ', ' + house.postal_code

                mortgage_type = ''
                if loan_request.mortgage_type == 1:
                    mortgage_type = 'Linear'
                elif loan_request.mortgage_type == 2:
                    mortgage_type = 'Fixed-Rate'

                row_count = self.loan_request_table.rowCount()
                self.loan_request_table.insertRow(row_count)
                self.loan_request_table.setItem(row_count, 0, QtWidgets.QTableWidgetItem(address))
                self.loan_request_table.setItem(row_count, 1, QtWidgets.QTableWidgetItem(mortgage_type))
                self.loan_request_table.setItem(row_count, 2, QtWidgets.QTableWidgetItem(str(
                    loan_request.amount_wanted)))
                self.loan_request_table.setItem(row_count, 3, QtWidgets.QTableWidgetItem(str(house.price)))

    def show_request(self):
        """
        Redirects to a Pending Loan Request 2 that shows more information about the request
        Shows "Select request" if the user did not choose any items in the table.
        """
        try:
            # Get the selected row index
            selected_index = self.loan_request_table.selectedIndexes()[0].row()
            # If a request has been selected, show it
            [loan_request, _] = self.loan_requests[selected_index]
            self.mainwindow.fiplr2_controller.setup_view(loan_request.id)
            self.mainwindow.navigation.switch_to_fiplr2()
        except IndexError:
            self.mainwindow.show_dialog("Select request", 'No loan requests have been selected.')
