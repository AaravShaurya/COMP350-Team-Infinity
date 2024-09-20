# COMP350-Team-Infinity
## 5 Sentence Summary

Introduction: The annual student government elections at our university have traditionally been conducted using Google Forms.

Related Work: Existing election systems like Election Buddy offer similar functionalities but are not suitable for our university’s budget, Google Forms is another commonly used tool.

Problem Statement: The use of Google Forms for student elections resulted in vulnerabilities such as potential breaches of voter anonymity, difficulty in preventing multiple submissions, and challenges in efficiently managing and verifying results.

Solution Proposal: We propose developing a dedicated election software system that integrates with the university’s ID system, ensuring secure, anonymous voting, preventing double voting, and providing real-time, transparent results.

Validation: The success of this system will be measured by its ability to eliminate the issues previously encountered with Google Forms, particularly in terms of security, anonymity, and result management, leading to its adoption for future elections at the university.

## Sequence Diagram 
(Image in docs folder labelled (Sequence Diagram.jpg))

### Actors: User (Voter), Admin, System.

### Processes:

User Login: The user accesses the login page and inputs their credentials (limited to specific IDs).

System Authentication: The system verifies user credentials.

Vote Casting: User selects their voting preferences.

Anonymity and Encryption: The system encrypts the vote to ensure anonymity.

Vote Submission: The user submits their vote.

Vote Storage: The system securely stores the encrypted vote.

Admin Access: Admin logs in to manage the election process, such as populating candidates.

Results Compilation: After voting ends, the system compiles the results.

Transparency Check: The system displays results publicly (without compromising individual votes). 

Double Voting Safeguard: System checks for and prevents any double-voting attempts. 

Confirmation: System sends an optional confirmation of the vote being successfully cast to the user.

## Getting Started

This section will guide you through setting up and running the election system locally.

First, clone the repository to your local machine:

```
git clone https://github.com/your-username/ease-my-vote.git
```

Secondly, Prepare Static HTML/CSS/JS Files

The HTML, CSS, and JavaScript files are located in the static directory.

Open the folder on VSCode, then open login.html. Right-click on the HTML file and choose 'Show Preview'. The address to access the website will be on the address bar. Copy the link and paste it into your browser. Otherwise, double-click on login.html in the directory.


