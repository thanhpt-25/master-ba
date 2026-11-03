# Business standards

## Order intake

An order is accepted only when the customer account is active and the credit limit is not exceeded.

Orders received after 15:00 Japan time are processed on the next business day.

## Shipping

Standard shipping takes three business days within Honshu and five business days to Okinawa.

Express shipping is available for parcels under 10 kilograms and costs a flat fee of 1,200 yen.

## Returns

A customer may return unopened goods within 14 days of delivery for a full refund.

Opened goods can be returned only when they are defective, and the refund excludes shipping.

## Invoicing

Invoices are issued on the last business day of each month and are payable within 30 days.

Late payment incurs an interest charge of 14.6 percent per year, calculated daily.

## Accounts

A user account is locked after five consecutive failed sign-in attempts and unlocks after 30 minutes.

Passwords must have at least 12 characters and must be changed every 180 days.

## Reports

The sales report is generated every Monday at 06:00 and covers the previous calendar week.

Inventory reports list every warehouse location with stock below the reorder point.

## Data retention

Order records are kept for seven years to satisfy tax regulations and are then deleted.

Access logs are kept for 90 days and are stored in a separate read-only archive.

## Performance

The order search screen must return results within two seconds for 95 percent of requests.

The system must support 300 concurrent users during the end-of-month closing period.

## Availability

Planned maintenance happens on the second Sunday of each month between 01:00 and 05:00.

The service availability target is 99.5 percent per month, excluding planned maintenance.

## Interfaces

Stock levels are sent to the warehouse system every 15 minutes as a CSV file over SFTP.

Payment results are received from the card gateway through a signed webhook call.
